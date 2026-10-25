use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fs::OpenOptions;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::os::unix::process::CommandExt;
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, Manager, State, WebviewUrl, WebviewWindowBuilder, WindowEvent};

const SCRIPTS: &str = "outputs/cloud-gpu-studio";

/// ComfyUI widgets can throw while drawing (for example the upload button of a
/// subgraph input in frontend 1.55). An uncaught error inside `draw()` breaks the
/// requestAnimationFrame chain, leaving a frozen canvas that no workflow switch can
/// recover. Guard the draw call so one broken widget cannot stop the whole canvas.
const COMFY_DRAW_GUARD: &str = r#"
(function () {
  if (window.__cloudGpuStudioDrawGuardInstalled) return;
  window.__cloudGpuStudioDrawGuardInstalled = true;
  function patch() {
    var app = window.app || (window.comfyAPI && window.comfyAPI.app && window.comfyAPI.app.app);
    var canvas = app && app.canvas;
    if (!canvas || canvas.__cloudGpuStudioDrawGuard) return;
    canvas.__cloudGpuStudioDrawGuard = true;
    var lastLog = 0;
    function report(error) {
      var now = Date.now();
      if (now - lastLog < 5000) return;
      lastLog = now;
      console.error('[Cloud GPU Studio] skipped a failing canvas draw:', error);
    }
    var drawWidgets = canvas.drawNodeWidgets;
    if (typeof drawWidgets === 'function') {
      canvas.drawNodeWidgets = function () {
        try {
          return drawWidgets.apply(this, arguments);
        } catch (error) {
          report(error);
        }
      };
    }
    var draw = canvas.draw;
    canvas.draw = function () {
      try {
        return draw.apply(this, arguments);
      } catch (error) {
        report(error);
      }
    };
  }
  patch();
  var tries = 0;
  var timer = setInterval(function () {
    patch();
    if (++tries > 80) clearInterval(timer);
  }, 250);
})();
"#;

fn project_root() -> PathBuf {
    if let Some(root) = std::env::var_os("CLOUD_GPU_STUDIO_HOME") {
        return PathBuf::from(root);
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(contents) = exe.parent().and_then(|macos| macos.parent()) {
            let resources = contents.join("Resources");
            if resources.join(SCRIPTS).join("cloud_control.py").is_file() {
                return resources;
            }
        }
        for parent in exe.ancestors() {
            if parent.join(SCRIPTS).join("cloud_control.py").is_file() {
                return parent.to_path_buf();
            }
        }
    }
    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

fn work_dir() -> PathBuf {
    if let Some(path) = std::env::var_os("CLOUD_GPU_STUDIO_WORK_DIR") {
        return PathBuf::from(path);
    }
    let root = project_root();
    if root.file_name().is_some_and(|name| name == "Resources") {
        return std::env::var_os("HOME").map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."))
            .join(".cloud-gpu-studio");
    }
    root.join("work")
}

fn comfy_dir() -> PathBuf {
    std::env::var_os("CLOUD_GPU_STUDIO_COMFYUI_DIR").map(PathBuf::from)
        .unwrap_or_else(|| std::env::var_os("HOME").map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from(".")) .join("ComfyUI"))
}

fn configure_child(process: &mut Command) {
    process.env("CLOUD_GPU_STUDIO_HOME", project_root())
        .env("CLOUD_GPU_STUDIO_WORK_DIR", work_dir());
}

#[derive(Default)]
struct Controller {
    busy: AtomicBool,
    launching: AtomicBool,
    cancelling: AtomicBool,
    launch_pid: AtomicU32,
    local_starting: AtomicBool,
    tunnel: Mutex<Option<Child>>,
    local: Mutex<Option<Child>>,
}

const IDLE_WAIT: Duration = Duration::from_secs(300);
const IDLE_WARNING: Duration = Duration::from_secs(15);

#[derive(Default)]
struct IdleGuard {
    enabled: bool,
    revision: u64,
    machine: Option<String>,
    idle_since: Option<Instant>,
    warning_since: Option<Instant>,
}

#[derive(Deserialize)]
struct IdleGuardConfig { enabled: bool }

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct IdleGuardView {
    enabled: bool,
    phase: &'static str,
    seconds_remaining: Option<u64>,
}

impl IdleGuard {
    fn view(&self) -> IdleGuardView {
        if !self.enabled {
            IdleGuardView { enabled: false, phase: "off", seconds_remaining: None }
        } else if let Some(since) = self.warning_since {
            IdleGuardView { enabled: true, phase: "warning",
                seconds_remaining: Some(IDLE_WARNING.as_secs().saturating_sub(since.elapsed().as_secs())) }
        } else if let Some(since) = self.idle_since {
            IdleGuardView { enabled: true, phase: "idle",
                seconds_remaining: Some(IDLE_WAIT.as_secs().saturating_sub(since.elapsed().as_secs())) }
        } else {
            IdleGuardView { enabled: true, phase: "waiting", seconds_remaining: None }
        }
    }

    fn clear_timer(&mut self) {
        self.idle_since = None;
        self.warning_since = None;
    }
}

fn idle_config_path() -> PathBuf { work_dir().join("idle-guard.json") }

fn load_idle_guard() -> IdleGuard {
    let enabled = std::fs::read(idle_config_path()).ok()
        .and_then(|bytes| serde_json::from_slice::<IdleGuardConfig>(&bytes).ok())
        .is_some_and(|config| config.enabled);
    IdleGuard { enabled, ..IdleGuard::default() }
}

fn save_idle_guard(enabled: bool) -> Result<(), String> {
    let path = idle_config_path();
    std::fs::create_dir_all(path.parent().ok_or("配置目录不存在")?).map_err(|e| e.to_string())?;
    let temporary = path.with_extension("json.tmp");
    std::fs::write(&temporary, if enabled { b"{\"enabled\":true}\n".as_slice() } else { b"{\"enabled\":false}\n".as_slice() })
        .map_err(|e| e.to_string())?;
    std::fs::rename(temporary, path).map_err(|e| e.to_string())
}

fn comfy_queue_empty(port: u16) -> Result<bool, String> {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_secs(2))
        .map_err(|e| e.to_string())?;
    stream.set_read_timeout(Some(Duration::from_secs(2))).map_err(|e| e.to_string())?;
    stream.write_all(b"GET /queue HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .map_err(|e| e.to_string())?;
    let mut response = Vec::new();
    stream.take(1024 * 1024).read_to_end(&mut response).map_err(|e| e.to_string())?;
    parse_comfy_queue(&response)
}

fn parse_comfy_queue(response: &[u8]) -> Result<bool, String> {
    let split = response.windows(4).position(|bytes| bytes == b"\r\n\r\n")
        .ok_or("ComfyUI 队列响应不完整")?;
    let header = String::from_utf8_lossy(&response[..split]);
    if !header.starts_with("HTTP/1.0 200 ") && !header.starts_with("HTTP/1.1 200 ") {
        return Err("ComfyUI 队列查询失败".into());
    }
    let value: Value = serde_json::from_slice(&response[split + 4..]).map_err(|e| e.to_string())?;
    let running = value["queue_running"].as_array().ok_or("缺少执行中队列")?;
    let pending = value["queue_pending"].as_array().ok_or("缺少待执行队列")?;
    Ok(running.is_empty() && pending.is_empty())
}

fn machine_running(status: &Status) -> bool {
    status.pod_status.as_deref().is_some_and(|value| value.eq_ignore_ascii_case("running"))
}

fn close_idle_warning(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("idle-warning") { let _ = window.close(); }
}

fn show_idle_warning(app: &AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("idle-warning") {
        window.show().map_err(|e| e.to_string())?;
        window.set_focus().map_err(|e| e.to_string())?;
        return Ok(());
    }
    WebviewWindowBuilder::new(app, "idle-warning", WebviewUrl::App("idle-warning.html".into()))
        .title("Cloud GPU Studio · 空闲提醒")
        .inner_size(440.0, 240.0)
        .resizable(false)
        .always_on_top(true)
        .center()
        .build().map_err(|e| e.to_string())?
        .set_focus().map_err(|e| e.to_string())?;
    Ok(())
}

fn idle_monitor(app: AppHandle, controller: Arc<Controller>, guard: Arc<Mutex<IdleGuard>>) {
    thread::spawn(move || loop {
        let warning = guard.lock().is_ok_and(|state| state.warning_since.is_some());
        thread::sleep(Duration::from_secs(if warning { 1 } else { 5 }));
        let enabled = guard.lock().is_ok_and(|state| state.enabled);
        if !enabled { continue; }
        // A failed status or queue check is unknown, never evidence of idleness.
        let status = read_status(&controller);
        let observation = status.ok().and_then(|s| {
            if s.busy || s.launching || !s.local_ready || !s.tunnel_ready
                || !machine_running(&s) { return None; }
            let machine = format!("{}:{}", s.provider, s.pod_id?);
            let local = comfy_queue_empty(8188).ok()?;
            let remote = comfy_queue_empty(8189).ok()?;
            Some((machine, local && remote))
        });
        let mut start_warning = false;
        let mut stop_warning = false;
        let mut delete_machine = None;
        if let Ok(mut state) = guard.lock() {
            if !state.enabled { continue; }
            match observation {
                Some((machine, idle)) => {
                    if state.machine.as_deref() != Some(&machine) {
                        state.machine = Some(machine.clone());
                        state.clear_timer();
                        stop_warning = true;
                    }
                    if idle {
                        let since = *state.idle_since.get_or_insert_with(Instant::now);
                        if since.elapsed() >= IDLE_WAIT && state.warning_since.is_none() {
                            state.warning_since = Some(Instant::now());
                            start_warning = true;
                        }
                        if state.warning_since.is_some_and(|time| time.elapsed() >= IDLE_WARNING) {
                            delete_machine = Some((machine, state.revision));
                            state.clear_timer();
                        }
                    } else {
                        stop_warning = state.warning_since.is_some();
                        state.clear_timer();
                    }
                }
                None => {
                    stop_warning = state.warning_since.is_some();
                    state.machine = None;
                    state.clear_timer();
                }
            }
        }
        if stop_warning { close_idle_warning(&app); }
        if start_warning {
            if let Err(error) = show_idle_warning(&app) {
                // A failed warning must never trigger a silent deletion.
                if let Ok(mut state) = guard.lock() { state.clear_timer(); }
                emit(&app, "idle-warning-error", format!("无法显示空闲提醒：{error}"), 0, None, "error");
            }
        }
        if let Some((machine, revision)) = delete_machine {
            close_idle_warning(&app);
            // Recheck identity and both queues at the moment of deletion.
            if begin(&controller).is_err() { continue; }
            let safe = read_status(&controller).ok().is_some_and(|s| {
                format!("{}:{}", s.provider, s.pod_id.as_deref().unwrap_or_default()) == machine
                    && s.local_ready && s.tunnel_ready
                    && machine_running(&s)
            }) && comfy_queue_empty(8188) == Ok(true) && comfy_queue_empty(8189) == Ok(true)
                && guard.lock().is_ok_and(|state| state.enabled && state.revision == revision
                    && state.machine.as_deref() == Some(&machine));
            if safe {
                emit(&app, "deleting", "ComfyUI 空闲超过 5 分钟且倒计时结束，正在自动删除云端机器…", 5, None, "info");
                let result = run_script_stream(&app, "stop", None, None);
                match result {
                    Ok(()) => {
                        if let Ok(mut tunnel) = controller.tunnel.lock() {
                            if let Some(mut child) = tunnel.take() { let _ = child.kill(); let _ = child.wait(); }
                        }
                        emit(&app, "deleted", "空闲云端机器已自动删除；本地作品仍保留。", 100, None, "success");
                    }
                    Err(error) => emit(&app, "error", format!("自动删除失败：{error}"), 0, None, "error"),
                }
                let _ = app.emit("deployment-finished", ());
            }
            controller.busy.store(false, Ordering::SeqCst);
        }
        if let Ok(state) = guard.lock() { let _ = app.emit("idle-guard-changed", state.view()); }
    });
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct Progress {
    phase: String,
    message: String,
    percent: u8,
    model_percent: Option<u8>,
    level: String,
}

fn emit(app: &AppHandle, phase: &str, message: impl Into<String>, percent: u8, model_percent: Option<u8>, level: &str) {
    let _ = app.emit("deployment-progress", Progress {
        phase: phase.into(), message: message.into(), percent, model_percent, level: level.into(),
    });
}

fn port_open(port: u16) -> bool {
    TcpStream::connect_timeout(&SocketAddr::from(([127, 0, 0, 1], port)), Duration::from_millis(300)).is_ok()
}

fn wait_port(port: u16, seconds: u64) -> bool {
    let deadline = Instant::now() + Duration::from_secs(seconds);
    while Instant::now() < deadline {
        if port_open(port) { return true; }
        thread::sleep(Duration::from_millis(800));
    }
    false
}

fn wait_port_closed(port: u16, seconds: u64) -> bool {
    let deadline = Instant::now() + Duration::from_secs(seconds);
    while Instant::now() < deadline {
        if !port_open(port) { return true; }
        thread::sleep(Duration::from_millis(300));
    }
    !port_open(port)
}

fn process_command(pid: u32) -> String {
    Command::new("ps").args(["-ww", "-p", &pid.to_string(), "-o", "command="]).output()
        .map(|output| String::from_utf8_lossy(&output.stdout).trim().to_string())
        .unwrap_or_default()
}

fn process_working_dir(pid: u32) -> Option<PathBuf> {
    let output = Command::new("lsof")
        .args(["-a", "-p", &pid.to_string(), "-d", "cwd", "-Fn"]).output().ok()?;
    String::from_utf8_lossy(&output.stdout)
        .lines().find_map(|line| line.strip_prefix('n').map(PathBuf::from))
}

/// Stop a local ComfyUI that was started outside the current app session.
/// Only a process listening on 8188 whose command references this checkout's
/// main.py, or whose working directory is the checkout, is terminated.
fn stop_listening_comfy() -> Result<bool, String> {
    let home = comfy_dir();
    let main = home.join("main.py");
    let output = Command::new("lsof").args(["-tiTCP:8188", "-sTCP:LISTEN"]).output()
        .map_err(|e| format!("无法查找本地 ComfyUI 进程：{e}"))?;
    let pids = String::from_utf8_lossy(&output.stdout);
    let mut stopped = false;
    for pid in pids.split_whitespace().filter_map(|value| value.parse::<u32>().ok()) {
        let command = process_command(pid);
        let matches = command.contains(main.to_string_lossy().as_ref())
            || process_working_dir(pid).is_some_and(|dir| dir == home);
        if !matches { continue; }
        let status = Command::new("kill").arg(pid.to_string()).status()
            .map_err(|e| format!("无法停止本地 ComfyUI：{e}"))?;
        if status.success() { stopped = true; }
    }
    Ok(stopped)
}

fn script(command: &str) -> Command {
    let mut process = Command::new("/usr/bin/python3");
    process.arg("-u").arg(project_root().join(SCRIPTS).join("cloud_control.py")).arg(command);
    configure_child(&mut process);
    process
}

fn parse_model_percent(line: &str) -> Option<u8> {
    if !line.contains("Model data:") { return None; }
    let start = line.rfind('(')? + 1;
    let end = line[start..].find('%')? + start;
    line[start..end].trim().parse().ok()
}

fn report_line(app: &AppHandle, line: &str) {
    let message = line.trim();
    if message.is_empty() { return; }
    if message == "GPU_SSH_READY" { let _ = app.emit("gpu-ssh-ready", ()); }
    let model = parse_model_percent(message);
    let (phase, percent) = if message == "INSTALL_DOWNLOAD_READY" {
        ("verifying", 82)
    } else if message == "PYTHON_DEPENDENCIES_READY" {
        ("installing", 65)
    } else if message == "CUDA13_ATTENTION_READY" {
        ("installing", 70)
    } else if message == "ALL_MODELS_VERIFIED" {
        ("downloading", 75)
    } else if message.starts_with("Created ") {
        ("booting", 9)
    } else if message.contains("waiting for SSH") || message.contains("SSH") {
        ("booting", 13)
    } else if let Some(value) = model {
        // Model bytes can reach 100% while pip is still installing. Keep the
        // combined stage below verification until both jobs have exited.
        ("downloading", 20 + (value as u16 * 55 / 100) as u8)
    } else if message.contains("Installing ComfyUI") || message.contains("Installing Python") || message.contains("Cloning") {
        ("installing", 17)
    } else if message.contains("Installing CUDA 13") {
        ("installing", 65)
    } else if message.contains("Waiting for model download") {
        ("downloading", 65)
    } else if message.contains("downloading") || message.contains("Downloading") {
        ("downloading", 20)
    } else if message.contains("Starting cloud ComfyUI") {
        ("verifying", 85)
    } else if message.contains("SHA256") || message.contains("Verified") || message.contains("checksum") {
        ("downloading", 75)
    } else if message.contains("CLOUD_READY") || message.contains("Cloud ComfyUI is ready") {
        ("cloud-ready", 88)
    } else {
        ("working", 20)
    };
    let display = match message {
        "PYTHON_DEPENDENCIES_READY" => "Python 依赖已安装，正在确认模型下载与校验状态…",
        "CUDA13_ATTENTION_READY" => "CUDA 13 加速算子已就绪，正在确认模型下载与校验状态…",
        "ALL_MODELS_VERIFIED" => "模型文件已下载并校验，正在确认 Python 依赖安装状态…",
        "INSTALL_DOWNLOAD_READY" => "模型与 Python 依赖均已就绪，正在校验并启动云端 ComfyUI…",
        _ => message,
    };
    emit(app, phase, display, percent, model, "info");
}

fn run_script_stream(app: &AppHandle, command: &str, offer: Option<(&str, f64)>, controller: Option<Arc<Controller>>) -> Result<(), String> {
    if controller.as_ref().is_some_and(|shared| shared.cancelling.load(Ordering::SeqCst)) {
        return Err("部署已取消。".into());
    }
    let control = project_root().join(SCRIPTS).join("cloud_control.py");
    if !control.exists() {
        return Err(format!("找不到云端控制脚本：{}", control.display()));
    }
    let mut process = script(command);
    if command == "start" || command == "resume" { process.process_group(0); }
    if let Some((id, limit)) = offer {
        process.env("CLOUD_GPU_STUDIO_OFFER_ID", id)
            .env("CLOUD_GPU_STUDIO_MAX_HOURLY", limit.to_string());
    }
    let mut child = process.stdout(Stdio::piped()).stderr(Stdio::piped())
        .spawn().map_err(|e| format!("无法运行部署脚本：{e}"))?;
    if let Some(shared) = &controller { shared.launch_pid.store(child.id(), Ordering::SeqCst); }
    let stderr = child.stderr.take().ok_or("无法读取脚本错误输出")?;
    let app_for_stderr = app.clone();
    let stderr_controller = controller.clone();
    let stderr_thread = thread::spawn(move || {
        for line in BufReader::new(stderr).lines().map_while(Result::ok) {
            if !stderr_controller.as_ref().is_some_and(|shared| shared.cancelling.load(Ordering::SeqCst)) {
                report_line(&app_for_stderr, &line);
            }
        }
    });
    let stdout = child.stdout.take().ok_or("无法读取脚本输出")?;
    for line in BufReader::new(stdout).lines().map_while(Result::ok) {
        if !controller.as_ref().is_some_and(|shared| shared.cancelling.load(Ordering::SeqCst)) {
            report_line(app, &line);
        }
    }
    let exit = child.wait().map_err(|e| format!("等待脚本结束失败：{e}"))?;
    if let Some(shared) = &controller { shared.launch_pid.store(0, Ordering::SeqCst); }
    let _ = stderr_thread.join();
    if exit.success() { Ok(()) } else { Err(format!("{command} 执行失败（退出码 {}），请查看上方日志。", exit.code().unwrap_or(-1))) }
}

fn cloud_exists() -> Result<bool, String> {
    let output = script("status").output().map_err(|e| format!("读取云端状态失败：{e}"))?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
    }
    let value: Value = serde_json::from_slice(&output.stdout).map_err(|e| format!("状态数据无效：{e}"))?;
    Ok(!value["pod"].is_null())
}

fn connect_tunnel(app: &AppHandle, controller: &Controller) -> Result<(), String> {
    if port_open(8189) {
        emit(app, "tunnel", "SSH 隧道已在 127.0.0.1:8189 运行", 93, None, "info");
        return Ok(());
    }
    emit(app, "tunnel", "正在建立 SSH 隧道…", 90, None, "info");
    let log_path = std::env::temp_dir().join("cloud-gpu-studio-tunnel.log");
    let log = OpenOptions::new().create(true).append(true).open(&log_path)
        .map_err(|e| format!("无法打开 SSH 日志：{e}"))?;
    let child = script("connect").stdout(Stdio::null()).stderr(Stdio::from(log))
        .spawn().map_err(|e| format!("SSH 隧道启动失败：{e}"))?;
    *controller.tunnel.lock().map_err(|_| "隧道状态锁定失败")? = Some(child);
    for _ in 0..90 {
        if controller.cancelling.load(Ordering::SeqCst) { return Err("部署已取消。".into()); }
        if port_open(8189) { return Ok(()); }
        thread::sleep(Duration::from_millis(500));
    }
    Err(format!("SSH 隧道未能连接。请查看 {}", log_path.display()))
}

fn tunnel_monitor(app: AppHandle, controller: Arc<Controller>) {
    thread::spawn(move || {
        let mut reconnect = false;
        loop {
            thread::sleep(Duration::from_secs(10));
            if let Ok(mut tunnel) = controller.tunnel.lock() {
                if let Some(child) = tunnel.as_mut() {
                    if child.try_wait().ok().flatten().is_some() {
                        tunnel.take();
                        reconnect = true;
                    }
                }
            }
            if !reconnect { continue; }
            if port_open(8189) {
                reconnect = false;
                continue;
            }
            if controller.launching.load(Ordering::SeqCst) || begin(&controller).is_err() {
                continue;
            }
            let result = match cloud_exists() {
                Ok(true) => connect_tunnel(&app, &controller),
                Ok(false) => {
                    reconnect = false;
                    Ok(())
                }
                Err(error) => Err(error),
            };
            controller.busy.store(false, Ordering::SeqCst);
            match result {
                Ok(()) if !reconnect => {},
                Ok(()) => {
                    reconnect = false;
                    emit(&app, "tunnel", "SSH 隧道已自动重新连接。", 100, None, "success");
                }
                Err(error) => {
                    if let Ok(mut tunnel) = controller.tunnel.lock() {
                        if let Some(mut child) = tunnel.take() {
                            let _ = child.kill();
                            let _ = child.wait();
                        }
                    }
                    eprintln!("SSH tunnel reconnect failed: {error}");
                }
            }
        }
    });
}

#[cfg(target_os = "macos")]
fn notify_cloud_ready() {
    thread::spawn(|| {
        let notification = Command::new("/usr/bin/osascript")
            .args(["-e", "display notification \"GPU 与 ComfyUI 已就绪，可以开始创作。 / GPU and ComfyUI are ready.\" with title \"Cloud GPU Studio\""])
            .stdout(Stdio::null()).stderr(Stdio::null()).spawn();
        let sound = Command::new("/usr/bin/afplay")
            .arg("/System/Library/Sounds/Glass.aiff")
            .stdout(Stdio::null()).stderr(Stdio::null()).spawn();
        if let Ok(mut child) = notification { let _ = child.wait(); }
        if let Ok(mut child) = sound { let _ = child.wait(); }
    });
}

#[cfg(not(target_os = "macos"))]
fn notify_cloud_ready() {}

fn start_local(app: &AppHandle, controller: &Controller, deployment_progress: bool) -> Result<(), String> {
    if port_open(8188) {
        if deployment_progress {
            emit(app, "local", "本地 ComfyUI 已在 127.0.0.1:8188 运行", 98, None, "info");
        }
        return Ok(());
    }
    if controller.local_starting.compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst).is_err() {
        return if wait_port(8188, 120) { Ok(()) } else { Err("本地 ComfyUI 启动超时。".into()) };
    }
    let result = (|| -> Result<(), String> {
        if deployment_progress { emit(app, "local", "正在启动本地 ComfyUI…", 95, None, "info"); }
        let log_path = std::env::temp_dir().join("cloud-gpu-studio-local.log");
        let log = OpenOptions::new().create(true).append(true).open(&log_path)
            .map_err(|e| format!("无法打开 ComfyUI 日志：{e}"))?;
        let log2 = log.try_clone().map_err(|e| e.to_string())?;
        let local = comfy_dir();
        if !local.join("main.py").is_file() || !local.join(".venv/bin/python").is_file() {
            return Err("本地 ComfyUI 尚未安装完成，请先使用下方的一键安装。".into());
        }
        let mut command = Command::new(local.join(".venv/bin/python"));
        configure_child(&mut command);
        let child = command.arg(local.join("main.py"))
            .args(["--cpu", "--listen", "127.0.0.1", "--port", "8188", "--disable-auto-launch", "--offline"])
            .current_dir(local)
            .stdin(Stdio::null()).stdout(Stdio::from(log)).stderr(Stdio::from(log2))
            .spawn().map_err(|e| format!("本地 ComfyUI 启动失败：{e}"))?;
        *controller.local.lock().map_err(|_| "本地服务状态锁定失败")? = Some(child);
        if wait_port(8188, 120) { Ok(()) } else { Err(format!("本地 ComfyUI 未能启动。请查看 {}", log_path.display())) }
    })();
    controller.local_starting.store(false, Ordering::SeqCst);
    result
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Status {
    provider: String,
    pod_id: Option<String>,
    pod_status: Option<String>,
    cost_per_hour: Option<f64>,
    balance: Option<f64>,
    old_volume_billed: bool,
    local_ready: bool,
    tunnel_ready: bool,
    busy: bool,
    launching: bool,
}

fn read_status(controller: &Controller) -> Result<Status, String> {
    let output = script("status").output().map_err(|e| format!("无法读取云端状态：{e}"))?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
    }
    let value: Value = serde_json::from_slice(&output.stdout).map_err(|e| format!("状态数据无效：{e}"))?;
    let pod = &value["pod"];
    Ok(Status {
        provider: value["provider"].as_str().unwrap_or("runpod").to_owned(),
        pod_id: pod["id"].as_str().map(str::to_owned),
        pod_status: pod["desiredStatus"].as_str().map(str::to_owned),
        cost_per_hour: pod["costPerHr"].as_f64().or_else(|| pod["costPerHr"].as_str().and_then(|v| v.parse().ok())),
        balance: value["balance"].as_f64().or_else(|| value["balance"].as_str().and_then(|v| v.parse().ok())),
        old_volume_billed: !value["old_network_volume_still_billed"].is_null(),
        local_ready: port_open(8188),
        tunnel_ready: port_open(8189),
        busy: controller.busy.load(Ordering::SeqCst),
        launching: controller.launching.load(Ordering::SeqCst),
    })
}

fn config_command(command: &str, payload: Option<Value>) -> Result<Value, String> {
    let mut process = Command::new("/usr/bin/python3");
    configure_child(&mut process);
    let mut child = process.arg(project_root().join(SCRIPTS).join("app_config.py")).arg(command)
        .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped())
        .spawn().map_err(|e| format!("无法读取配置：{e}"))?;
    if let Some(value) = payload {
        let bytes = serde_json::to_vec(&value).map_err(|e| e.to_string())?;
        child.stdin.take().ok_or("无法传入配置")?.write_all(&bytes).map_err(|e| e.to_string())?;
    }
    let output = child.wait_with_output().map_err(|e| e.to_string())?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
    }
    serde_json::from_slice(&output.stdout).map_err(|e| format!("配置响应无效：{e}"))
}

fn validate_max_price(value: f64) -> Result<(), String> {
    if value.is_finite() && value > 0.0 { Ok(()) }
    else { Err("每小时价格上限必须是高于 $0 的有限数字。".into()) }
}

#[tauri::command]
async fn get_gpu_offers(max_price: Option<f64>) -> Result<Value, String> {
    if let Some(limit) = max_price { validate_max_price(limit)?; }
    tauri::async_runtime::spawn_blocking(move || {
        let mut process = script("offers");
        if let Some(limit) = max_price { process.env("CLOUD_GPU_STUDIO_MAX_HOURLY", limit.to_string()); }
        let output = process
            .output().map_err(|e| format!("查询显卡报价失败：{e}"))?;
        if !output.status.success() {
            return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
        }
        serde_json::from_slice(&output.stdout).map_err(|e| format!("报价响应无效：{e}"))
    }).await.map_err(|e| e.to_string())?
}

#[tauri::command]
async fn get_host_metrics() -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(|| {
        let output = script("metrics").output().map_err(|e| format!("读取远程指标失败：{e}"))?;
        if !output.status.success() {
            return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
        }
        serde_json::from_slice(&output.stdout).map_err(|e| format!("远程指标响应无效：{e}"))
    }).await.map_err(|e| e.to_string())?
}

fn local_comfy_command(command: &str) -> Command {
    let mut process = Command::new("/usr/bin/python3");
    process.arg("-u").arg(project_root().join(SCRIPTS).join("comfy_local.py")).arg(command);
    configure_child(&mut process);
    process
}

fn local_comfy_state(command: &str) -> Result<Value, String> {
    let output = local_comfy_command(command).output().map_err(|e| e.to_string())?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
    }
    serde_json::from_slice(&output.stdout).map_err(|e| format!("本地 ComfyUI 状态无效：{e}"))
}

#[tauri::command]
async fn get_local_comfy_status() -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(|| local_comfy_state("status"))
        .await.map_err(|e| e.to_string())?
}

#[tauri::command]
async fn check_local_comfy_update() -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(|| local_comfy_state("check"))
        .await.map_err(|e| e.to_string())?
}

#[tauri::command]
fn manage_local_comfy(app: AppHandle, controller: State<'_, Arc<Controller>>, action: String) -> Result<(), String> {
    if action != "install" && action != "update" { return Err("不支持的 ComfyUI 操作。".into()); }
    begin(&controller)?;
    let shared = controller.inner().clone();
    thread::spawn(move || {
        let result = (|| -> Result<(), String> {
            let mut child = local_comfy_command(&action)
                .stdout(Stdio::piped()).stderr(Stdio::piped())
                .spawn().map_err(|e| format!("无法执行 ComfyUI 操作：{e}"))?;
            let stderr = child.stderr.take().ok_or("无法读取安装日志")?;
            let app_for_stderr = app.clone();
            let stderr_thread = thread::spawn(move || {
                for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                    let _ = app_for_stderr.emit("comfy-progress", line);
                }
            });
            let stdout = child.stdout.take().ok_or("无法读取安装进度")?;
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                let _ = app.emit("comfy-progress", line);
            }
            let status = child.wait().map_err(|e| e.to_string())?;
            let _ = stderr_thread.join();
            if status.success() { Ok(()) } else { Err("本地 ComfyUI 操作失败，请查看上方进度信息。".into()) }
        })();
        let outcome = match result {
            Ok(()) => serde_json::json!({"ok": true, "message": "操作完成。"}),
            Err(error) => serde_json::json!({"ok": false, "message": error}),
        };
        let _ = app.emit("comfy-finished", outcome);
        shared.busy.store(false, Ordering::SeqCst);
        let _ = app.emit("deployment-finished", ());
    });
    Ok(())
}

#[tauri::command]
async fn stop_local_comfy(app: AppHandle, controller: State<'_, Arc<Controller>>) -> Result<(), String> {
    let shared = controller.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        if let Some(mut child) = shared.local.lock().map_err(|_| "本地服务状态锁定失败")?.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
        let find_error = stop_listening_comfy().err();
        if !wait_port_closed(8188, 10) {
            let detail = find_error.map(|error| format!("（{error}）")).unwrap_or_default();
            return Err(format!("本地 ComfyUI 仍在运行，请在终端中关闭后重试{detail}。"));
        }
        if let Some(window) = app.get_webview_window("comfy") {
            let _ = window.close();
        }
        Ok(())
    }).await.map_err(|e| format!("停止本地 ComfyUI 任务失败：{e}"))?
}

#[tauri::command]
async fn get_settings() -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(|| config_command("settings", None))
        .await.map_err(|e| e.to_string())?
}

#[tauri::command]
async fn save_settings(settings: Value) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || config_command("save", Some(settings)))
        .await.map_err(|e| e.to_string())?
}

#[tauri::command]
async fn save_api_key(provider: String, key: String) -> Result<Value, String> {
    let value = serde_json::json!({"provider": provider, "key": key});
    tauri::async_runtime::spawn_blocking(move || config_command("key", Some(value)))
        .await.map_err(|e| e.to_string())?
}

#[tauri::command]
async fn inspect_hf_model(url: String) -> Result<Value, String> {
    let value = serde_json::json!({"url": url});
    tauri::async_runtime::spawn_blocking(move || config_command("inspect", Some(value)))
        .await.map_err(|e| e.to_string())?
}

#[tauri::command]
async fn save_model_pack(urls: Value) -> Result<Value, String> {
    let value = serde_json::json!({"urls": urls});
    tauri::async_runtime::spawn_blocking(move || config_command("save-pack", Some(value)))
        .await.map_err(|e| e.to_string())?
}

#[tauri::command]
fn prepare_video_mode(app: AppHandle, controller: State<'_, Arc<Controller>>, mode: &'static str) -> Result<(), String> {
    begin(&controller)?;
    let shared = controller.inner().clone();
    thread::spawn(move || {
        let result = (|| -> Result<(), String> {
            let mut child = script(&format!("prepare-{mode}")).stdout(Stdio::piped()).stderr(Stdio::piped())
                .spawn().map_err(|e| format!("无法启动 {mode} 下载：{e}"))?;
            let stderr = child.stderr.take().ok_or("无法读取下载错误")?;
            let error_thread = thread::spawn(move || {
                BufReader::new(stderr).lines().map_while(Result::ok).collect::<Vec<_>>().join("\n")
            });
            let stdout = child.stdout.take().ok_or("无法读取下载进度")?;
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                let _ = app.emit("video-mode-progress", line);
            }
            let status = child.wait().map_err(|e| e.to_string())?;
            let errors = error_thread.join().unwrap_or_default();
            if status.success() { Ok(()) } else { Err(errors) }
        })();
        let outcome = match result {
            Ok(()) => serde_json::json!({"ok": true, "message": format!("{mode} 模型已下载并校验，可以切换。")}),
            Err(error) => serde_json::json!({"ok": false, "message": error}),
        };
        let _ = app.emit("video-mode-finished", outcome);
        shared.busy.store(false, Ordering::SeqCst);
        let _ = app.emit("deployment-finished", ());
    });
    Ok(())
}

#[tauri::command]
fn prepare_ref2va(app: AppHandle, controller: State<'_, Arc<Controller>>) -> Result<(), String> {
    prepare_video_mode(app, controller, "ref2va")
}

#[tauri::command]
fn prepare_fl2va(app: AppHandle, controller: State<'_, Arc<Controller>>) -> Result<(), String> {
    prepare_video_mode(app, controller, "fl2va")
}

#[tauri::command]
async fn get_status(controller: State<'_, Arc<Controller>>) -> Result<Status, String> {
    let shared = controller.inner().clone();
    tauri::async_runtime::spawn_blocking(move || read_status(&shared))
        .await.map_err(|e| format!("状态任务失败：{e}"))?
}

fn begin(controller: &Controller) -> Result<(), String> {
    controller.busy.compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
        .map(|_| ()).map_err(|_| "另一项操作正在进行，请等待完成。".to_string())
}

#[tauri::command]
fn get_idle_guard(guard: State<'_, Arc<Mutex<IdleGuard>>>) -> Result<IdleGuardView, String> {
    guard.lock().map(|state| state.view()).map_err(|e| e.to_string())
}

#[tauri::command]
fn set_idle_guard(app: AppHandle, guard: State<'_, Arc<Mutex<IdleGuard>>>, enabled: bool) -> Result<IdleGuardView, String> {
    save_idle_guard(enabled)?;
    let view = {
        let mut state = guard.lock().map_err(|e| e.to_string())?;
        state.enabled = enabled;
        state.revision = state.revision.wrapping_add(1);
        state.machine = None;
        state.clear_timer();
        state.view()
    };
    close_idle_warning(&app);
    let _ = app.emit("idle-guard-changed", &view);
    Ok(view)
}

#[tauri::command]
fn keep_idle_machine(app: AppHandle, guard: State<'_, Arc<Mutex<IdleGuard>>>) -> Result<(), String> {
    let mut state = guard.lock().map_err(|e| e.to_string())?;
    state.revision = state.revision.wrapping_add(1);
    if state.machine.is_some() {
        state.warning_since = None;
        state.idle_since = Some(Instant::now());
    }
    let view = state.view();
    drop(state);
    close_idle_warning(&app);
    let _ = app.emit("idle-guard-changed", view);
    Ok(())
}

#[tauri::command]
fn delete_idle_machine(app: AppHandle, controller: State<'_, Arc<Controller>>,
                       guard: State<'_, Arc<Mutex<IdleGuard>>>) -> Result<(), String> {
    {
        let mut state = guard.lock().map_err(|e| e.to_string())?;
        state.revision = state.revision.wrapping_add(1);
        state.clear_timer();
    }
    close_idle_warning(&app);
    delete_cloud(app, controller)
}

#[tauri::command]
fn launch(app: AppHandle, controller: State<'_, Arc<Controller>>,
          offer_id: Option<String>, max_price: Option<f64>) -> Result<(), String> {
    begin(&controller)?;
    let shared = controller.inner().clone();
    shared.launching.store(true, Ordering::SeqCst);
    shared.cancelling.store(false, Ordering::SeqCst);
    thread::spawn(move || {
        let local_app = app.clone();
        let local_controller = shared.clone();
        let local_worker = thread::spawn(move || start_local(&local_app, &local_controller, false));
        let result = (|| -> Result<(), String> {
            if shared.cancelling.load(Ordering::SeqCst) { return Ok(()); }
            let existing = cloud_exists()?;
            if shared.cancelling.load(Ordering::SeqCst) { return Ok(()); }
            if existing {
                emit(&app, "booting", "检测到已有云端机器，正在检查并继续部署…", 15, None, "info");
                run_script_stream(&app, "resume", None, Some(shared.clone()))?;
            } else {
                let id = offer_id.as_deref().filter(|value| !value.is_empty())
                    .ok_or("请先查询报价并选择一台显卡。")?;
                let limit = max_price.ok_or("缺少所选报价的价格保护值，请刷新报价后再试。")?;
                validate_max_price(limit)?;
                if shared.cancelling.load(Ordering::SeqCst) { return Ok(()); }
                emit(&app, "creating", format!("正在核对所选显卡与 ${limit:.2}/小时价格上限…"), 3, None, "info");
                run_script_stream(&app, "start", Some((id, limit)), Some(shared.clone()))?;
            }
            if shared.cancelling.load(Ordering::SeqCst) { return Ok(()); }
            connect_tunnel(&app, &shared)?;
            if shared.cancelling.load(Ordering::SeqCst) { return Ok(()); }
            emit(&app, "local", "正在确认本地 ComfyUI 已就绪…", 95, None, "info");
            while !local_worker.is_finished() {
                if shared.cancelling.load(Ordering::SeqCst) { return Ok(()); }
                thread::sleep(Duration::from_millis(200));
            }
            local_worker.join().map_err(|_| "本地 ComfyUI 启动任务异常终止")??;
            if shared.cancelling.load(Ordering::SeqCst) { return Ok(()); }
            emit(&app, "ready", "云端已连接，ComfyUI 可以使用了。", 100, None, "success");
            notify_cloud_ready();
            Ok(())
        })();
        shared.launching.store(false, Ordering::SeqCst);
        if !shared.cancelling.load(Ordering::SeqCst) {
            if let Err(error) = result { emit(&app, "error", error, 0, None, "error"); }
            shared.busy.store(false, Ordering::SeqCst);
            let _ = app.emit("deployment-finished", ());
        }
    });
    Ok(())
}

fn interrupt_launch(app: AppHandle, shared: Arc<Controller>, delete_after: bool) -> Result<(), String> {
    if !shared.launching.load(Ordering::SeqCst) {
        return Err("没有正在进行的机器部署。".into());
    }
    shared.cancelling.compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
        .map_err(|_| "正在取消部署，请稍候。".to_string())?;
    thread::spawn(move || {
        let phase = if delete_after { "deleting" } else { "cancelling" };
        emit(&app, phase, "正在等待机器创建请求结束，然后停止部署…", 10, None, "info");
        while shared.launching.load(Ordering::SeqCst) {
            if matches!(cloud_exists(), Ok(true)) { break; }
            thread::sleep(Duration::from_millis(500));
        }
        let stopped = if delete_after {
            emit(&app, "deleting", "正在删除云端机器及临时磁盘…", 45, None, "info");
            run_script_stream(&app, "stop", None, None)
        } else {
            emit(&app, "cancelling", "正在停止安装、下载和连接；云端机器将保留。", 60, None, "info");
            Ok(())
        };
        let mut signalled_pid = shared.launch_pid.load(Ordering::SeqCst);
        if signalled_pid != 0 {
            // Keep the paid instance on cancellation; terminate only the local
            // deployment process group and its SSH/downloader descendants.
            let _ = Command::new("/bin/kill").arg("-TERM").arg(format!("-{signalled_pid}")).status();
        }
        if let Ok(mut tunnel) = shared.tunnel.lock() {
            if let Some(mut child) = tunnel.take() { let _ = child.kill(); let _ = child.wait(); }
        }
        let waiting_since = Instant::now();
        let mut reported_wait = false;
        let mut forced_exit = false;
        while shared.launching.load(Ordering::SeqCst) {
            let pid = shared.launch_pid.load(Ordering::SeqCst);
            if pid != 0 && pid != signalled_pid {
                let _ = Command::new("/bin/kill").arg("-TERM").arg(format!("-{pid}")).status();
                signalled_pid = pid;
            }
            if !reported_wait && waiting_since.elapsed() >= Duration::from_secs(10) {
                emit(&app, phase, "正在等待部署进程退出；机器状态不会因此改变。", 75, None, "info");
                reported_wait = true;
            }
            if !forced_exit && waiting_since.elapsed() >= Duration::from_secs(20) {
                let pid = shared.launch_pid.load(Ordering::SeqCst);
                if pid != 0 {
                    let _ = Command::new("/bin/kill").arg("-KILL").arg(format!("-{pid}")).status();
                }
                forced_exit = true;
            }
            thread::sleep(Duration::from_millis(500));
        }
        let result = if !delete_after {
            stopped
        } else {
            match cloud_exists() {
                Ok(false) => Ok(()),
                Ok(true) => Err(stopped.err().unwrap_or_else(|| "机器仍在运行，请重试删除。".into())),
                Err(error) => Err(format!("无法确认机器是否已删除：{error}")),
            }
        };
        match result {
            Ok(()) => {
                if delete_after {
                    emit(&app, "deleted", "部署已取消，云端机器及临时磁盘已删除。", 100, None, "success");
                } else {
                    emit(&app, "cancelled", "部署已取消，云端机器仍在计费。可继续部署或单独删除机器。", 100, None, "success");
                }
            }
            Err(error) => emit(&app, "error", error, 0, None, "error"),
        }
        shared.cancelling.store(false, Ordering::SeqCst);
        shared.busy.store(false, Ordering::SeqCst);
        let _ = app.emit("deployment-finished", ());
    });
    Ok(())
}

#[tauri::command]
fn cancel_launch(app: AppHandle, controller: State<'_, Arc<Controller>>) -> Result<(), String> {
    interrupt_launch(app, controller.inner().clone(), false)
}

#[tauri::command]
fn delete_cloud(app: AppHandle, controller: State<'_, Arc<Controller>>) -> Result<(), String> {
    if controller.launching.load(Ordering::SeqCst) {
        return interrupt_launch(app, controller.inner().clone(), true);
    }
    begin(&controller)?;
    let shared = controller.inner().clone();
    thread::spawn(move || {
        emit(&app, "deleting", "正在删除云端机器及临时磁盘…", 10, None, "info");
        let result = run_script_stream(&app, "stop", None, None);
        match result {
            Ok(()) => {
                if let Ok(mut tunnel) = shared.tunnel.lock() {
                    if let Some(mut child) = tunnel.take() { let _ = child.kill(); let _ = child.wait(); }
                }
                emit(&app, "deleted", "云端机器已删除；本地图片和视频仍保留。", 100, None, "success");
            }
            Err(error) => emit(&app, "error", error, 0, None, "error"),
        }
        shared.busy.store(false, Ordering::SeqCst);
        let _ = app.emit("deployment-finished", ());
    });
    Ok(())
}

#[tauri::command]
async fn open_comfy_window(app: AppHandle, controller: State<'_, Arc<Controller>>) -> Result<(), String> {
    let shared = controller.inner().clone();
    let worker_app = app.clone();
    tauri::async_runtime::spawn_blocking(move || start_local(&worker_app, &shared, false))
        .await.map_err(|e| format!("本地 ComfyUI 启动任务失败：{e}"))??;
    if let Some(window) = app.get_webview_window("comfy") {
        let _ = window.eval(COMFY_DRAW_GUARD);
        window.show().map_err(|e| e.to_string())?;
        window.set_focus().map_err(|e| e.to_string())?;
        return Ok(());
    }
    let url = "http://127.0.0.1:8188/".parse().map_err(|e| format!("ComfyUI 地址无效：{e}"))?;
    WebviewWindowBuilder::new(&app, "comfy", WebviewUrl::External(url))
        .title("ComfyUI · Cloud GPU Studio")
        .inner_size(1440.0, 900.0)
        .initialization_script(COMFY_DRAW_GUARD)
        .build().map_err(|e| format!("无法打开 ComfyUI 窗口：{e}"))?;
    Ok(())
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .manage(Arc::new(Controller::default()))
        .manage(Arc::new(Mutex::new(load_idle_guard())))
        .setup(|app| {
            let controller = app.state::<Arc<Controller>>().inner().clone();
            let guard = app.state::<Arc<Mutex<IdleGuard>>>().inner().clone();
            idle_monitor(app.handle().clone(), controller.clone(), guard);
            tunnel_monitor(app.handle().clone(), controller);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![get_status, get_settings, save_settings,
            save_api_key, inspect_hf_model, save_model_pack, prepare_ref2va, prepare_fl2va, get_local_comfy_status,
            check_local_comfy_update, manage_local_comfy, stop_local_comfy, get_gpu_offers, get_host_metrics,
            launch, cancel_launch, delete_cloud, open_comfy_window,
            get_idle_guard, set_idle_guard, keep_idle_machine, delete_idle_machine])
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                let state = window.app_handle().state::<Arc<Controller>>();
                if window.label() == "main" && state.busy.load(Ordering::SeqCst) {
                    api.prevent_close();
                    emit(&window.app_handle(), "working", "操作正在进行，请等当前步骤结束后再关闭窗口。", 0, None, "info");
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("failed to build Cloud GPU Studio desktop app")
        .run(|app, event| {
            if let tauri::RunEvent::ExitRequested { api, .. } = event {
                let state = app.state::<Arc<Controller>>();
                if state.busy.load(Ordering::SeqCst) {
                    api.prevent_exit();
                    emit(app, "working", "操作正在进行，请等当前步骤结束后再退出应用。", 0, None, "info");
                }
            }
        });
}

#[cfg(test)]
mod idle_tests {
    use super::*;

    #[test]
    fn queue_must_be_empty_on_both_lists() {
        fn response(body: &str) -> Vec<u8> {
            format!("HTTP/1.0 200 OK\r\nContent-Length: {}\r\n\r\n{body}", body.len()).into_bytes()
        }
        assert_eq!(parse_comfy_queue(&response(r#"{"queue_running":[],"queue_pending":[]}"#)), Ok(true));
        assert_eq!(parse_comfy_queue(&response(r#"{"queue_running":[[1]],"queue_pending":[]}"#)), Ok(false));
        assert_eq!(parse_comfy_queue(&response(r#"{"queue_running":[],"queue_pending":[[2]]}"#)), Ok(false));
        assert!(parse_comfy_queue(&response(r#"{"queue_running":[]}"#)).is_err());
        assert!(parse_comfy_queue(b"HTTP/1.0 503 Unavailable\r\n\r\n{}").is_err());
    }

    #[test]
    fn warning_countdown_is_bounded() {
        let state = IdleGuard { enabled: true, warning_since: Some(Instant::now() - Duration::from_secs(3)), ..IdleGuard::default() };
        assert_eq!(state.view().phase, "warning");
        assert!(state.view().seconds_remaining.unwrap() <= 12);
    }
}
