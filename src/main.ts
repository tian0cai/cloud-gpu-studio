import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { check, type Update } from '@tauri-apps/plugin-updater';
import { relaunch } from '@tauri-apps/plugin-process';
import { currentLanguage, setLanguage, startI18n } from './i18n';
import './style.css';

type Status = {
  provider: 'runpod' | 'vast';
  podId: string | null;
  podStatus: string | null;
  costPerHour: number | null;
  balance: number | null;
  oldVolumeBilled: boolean;
  localReady: boolean;
  tunnelReady: boolean;
  busy: boolean;
  launching: boolean;
};
type ModelFile = { repo: string; revision: string; filename: string; destination: string; size: number; sha256: string };
type ImageModel = 'qwen' | 'local-qwen' | 'checkpoint' | 'none';
type VideoModel = 'h3' | 'local-h3' | 'none';
type LocalPack = { ready: true; image: Record<string, string>; video: Record<string, string>; urls: Record<'qwen' | 'h3', Record<string, string>>; size_gb: number } | { ready: false; error: string };
type Settings = { provider: 'runpod' | 'vast'; image_model: ImageModel; video_model: VideoModel; video_mode: 'fl2va' | 'ref2va'; ref2va_ready: boolean; fl2va_ready: boolean; custom_model: ModelFile | null; local_models_available: boolean; local_pack: LocalPack; keys: Record<'runpod' | 'vast', boolean> };
type Progress = {
  phase: string;
  message: string;
  percent: number;
  modelPercent: number | null;
  level: 'info' | 'success' | 'error';
};
type LocalComfy = { path: string; installed: boolean; python_ready: boolean; bridge_ready: boolean; git_ready: boolean; version: string | null; update_available: boolean | null; error: string | null };
type GpuOffer = { id: string; gpu: string; price: number; location: string; vramGb: number; reliability: number | null };
type HostMetrics = { online: boolean; message?: string; cpuPercent?: number | null; gpuPercent?: number | null; ramUsedGb?: number | null; ramTotalGb?: number | null; vramUsedGb?: number | null; vramTotalGb?: number | null };

const app = document.querySelector<HTMLDivElement>('#app')!;
app.innerHTML = `
  <div class="shell">
    <aside class="sidebar">
      <div class="brand"><img class="brand-icon" src="/brand-mark.svg" alt=""><div><strong>Cloud GPU Studio</strong><small>COMFYUI CONTROL</small></div></div>
      <div class="section-label">控制中心</div>
      <nav class="side-menu" aria-label="主导航">
        <button class="side-nav active" data-nav="home" type="button"><span>◫</span> 总览</button>
        <button class="side-nav" data-nav="models" type="button"><span>✳</span> 模型方案</button>
        <button class="side-nav" data-nav="machines" type="button"><span>▧</span> 云端机器</button>
        <button class="side-nav" data-nav="comfy" type="button"><span>⌘</span> ComfyUI</button>
        <button class="side-nav" data-nav="settings" type="button"><span>⚙</span> 账户设置</button>
      </nav>
      <div class="sidebar-bottom"><label class="language-control">语言 / Language<select id="ui-language" aria-label="Interface language"><option value="zh-CN">简体中文</option><option value="en-US">English</option></select></label><div class="privacy-line"><div class="privacy-dot"></div><span>凭证仅保存在本机</span></div></div>
    </aside>
    <main class="main">
      <header class="topbar"><div><div id="page-eyebrow" class="eyebrow">YOUR CREATIVE WORKSPACE</div><h1 id="page-title">创作工作台</h1><p id="page-subtitle">模型、算力和本地 ComfyUI，一眼掌握。</p></div><div class="header-art" aria-hidden="true"><div class="header-orbit orbit-one"></div><div class="header-orbit orbit-two"></div><img class="header-mark" src="/brand-mark.svg" alt=""></div><div id="top-status" class="top-status"><span class="pulse"></span> 正在检查状态</div></header>
      <section class="dashboard">
        <div class="config-card"><div class="section-head"><div><div class="eyebrow">MODEL SELECTION</div><h3>选择创作模型</h3></div><span id="config-state" class="config-state">读取中</span></div>
          <div class="model-grid"><label>图片模型<select id="image-model"><option value="qwen">官方 Qwen Image 2.1</option><option value="local-qwen">自定义 Qwen 组件包</option><option value="checkpoint">Hugging Face SD/SDXL checkpoint</option><option value="none">不部署图片模型</option></select></label><label>视频模型<select id="video-model"><option value="h3">官方 MiniMax H3 INT8</option><option value="local-h3">自定义 H3 组件包</option><option value="none">不部署视频模型</option></select></label></div>
          <div id="custom-row" class="custom-row" hidden><label>图片 checkpoint 文件链接<input id="model-url" type="url" placeholder="https://huggingface.co/owner/repo/blob/main/model.safetensors" spellcheck="false"></label><button id="inspect-model" type="button">检查模型</button><small id="model-info">仅支持单文件 SD/SDXL checkpoint；视频模型请使用兼容的组件包。</small></div>
          <details id="pack-details" class="pack-details"><summary>自选组件包 · 编码器、VAE、LoRA</summary><div id="pack-summary"></div>
            <div class="pack-editor"><div><strong>图片 · Qwen 架构</strong><label>主模型<input data-pack-kind="qwen" data-pack-role="unet" type="url" placeholder="Hugging Face 文件链接"></label><label>文本编码器<input data-pack-kind="qwen" data-pack-role="clip" type="url" placeholder="Hugging Face 文件链接"></label><label>VAE<input data-pack-kind="qwen" data-pack-role="vae" type="url" placeholder="Hugging Face 文件链接"></label></div>
            <div><strong>视频 · H3 FL2VA 架构</strong><label>主模型<input data-pack-kind="h3" data-pack-role="unet" type="url" placeholder="Hugging Face 文件链接"></label><label>文本编码器<input data-pack-kind="h3" data-pack-role="clip" type="url" placeholder="Hugging Face 文件链接"></label><label>视频 VAE<input data-pack-kind="h3" data-pack-role="video_vae" type="url" placeholder="Hugging Face 文件链接"></label><label>音频 VAE<input data-pack-kind="h3" data-pack-role="audio_vae" type="url" placeholder="Hugging Face 文件链接"></label><label>LoRA（可选）<input data-pack-kind="h3" data-pack-role="lora" type="url" placeholder="可留空"></label></div></div>
            <div class="pack-actions"><button id="save-pack" type="button">检查并保存组件包</button><span id="pack-status">每个链接会锁定版本、大小与 SHA-256；只支持上述两种节点架构。</span></div><p>组件包保存在本机受限目录，不会写入公共仓库。多参考模式使用独立的 Ref2VA 主模型；现有 H3 文本编码器和 VAE 会复用，LoRA 需另行验证适配。</p></details>
          <div class="provider-row"><label>云平台<select id="provider"><option value="runpod">RunPod</option><option value="vast">Vast.ai</option></select></label></div>
          <div class="config-actions"><button id="save-config" type="button">保存模型与平台</button><span id="config-message">选择会在下一次新建机器时生效。</span></div>
          <div class="mode-panel"><div><strong>H3 视频模式</strong><small id="mode-state">多参考 Ref2VA 已启用</small></div><div class="mode-actions"><button id="download-ref2va" type="button">下载多参考模型</button><button id="switch-ref2va" type="button">切换到多参考</button><button id="download-fl2va" type="button">下载首帧模型</button><button id="switch-fl2va" type="button">切回首帧模式</button></div><small id="mode-progress">新机器优先下载 Ref2VA；首帧 FL2VA 可在机器启动后按需下载。</small></div>
          <p class="config-footnote">新建机器预留双模式磁盘：RunPod 180 GB、Vast.ai 200 GB；磁盘费用由平台计入报价或另行计费。兼容的 80 GB 以上单卡，按需实例；Vast.ai 累计费用达到 $9 自动删除，RunPod 保留原 3 小时限制。报价筛选可留空。</p>
        </div>
        <div class="offer-card"><div class="section-head"><div><div class="eyebrow">LIVE GPU MARKET</div><h3>选择显卡与价格</h3></div><span id="offer-count" class="offer-count">尚未查询</span></div>
          <div class="offer-controls"><label>每小时价格筛选（美元，可留空）<input id="max-price" type="number" min="0.001" step="0.001" placeholder="不限"></label><label>显卡型号<select id="gpu-filter"><option value="">全部兼容型号</option></select></label><button id="query-offers" type="button">查询实时报价</button></div>
          <p id="offer-message" class="offer-message">保存模型与平台后查询报价，再选择一台机器；启动时会重新核对库存和价格。</p><div id="gpu-offers" class="offer-list"></div>
        </div>
        <div class="hero">
          <div class="hero-copy"><div class="hero-kicker">INSTANCE CONTROL</div><h2>启动云端机器</h2><p>可先在 ComfyUI 页面编辑工作流，再按模型方案启动云端 GPU。</p>
          <div class="actions"><button id="launch" class="primary">启动并连接 <span>↗</span></button><button id="open-comfy" class="open-comfy" disabled>打开 ComfyUI ↗</button><button id="stop-comfy" type="button" disabled title="停止本地 ComfyUI 进程（127.0.0.1:8188）">关闭 ComfyUI</button><button id="cancel-launch" type="button" hidden>取消部署</button><button id="delete" class="danger" disabled>删除云端机器</button></div>
          <div class="hero-note">取消部署会保留仍在计费的机器；只有点击“删除云端机器”才会释放它。关闭应用也不会自动删除机器。</div></div>
        </div>
        <div class="metrics"><div class="metric"><span>云端机器</span><strong id="pod-value">检查中</strong><small id="pod-detail">云端实例</small></div><div class="metric"><span>运行价格</span><strong id="price-value">—</strong><small>美元 / 小时</small></div><div class="metric"><span>账户余额</span><strong id="balance-value">—</strong><small>美元</small></div><div class="metric"><span>连接状态</span><strong id="connection-value">检查中</strong><small id="connection-detail">本地端口 8188 / 8189</small></div></div>
        <div class="telemetry"><div class="section-head"><div><div class="eyebrow">LIVE TELEMETRY</div><h3>远程资源使用情况</h3></div><span id="telemetry-status">云端未启动</span></div><div class="telemetry-grid">
          <div class="telemetry-item"><span>CPU 使用率</span><strong id="cpu-value">—</strong><svg viewBox="0 0 100 30" preserveAspectRatio="none" role="img" aria-label="CPU 使用率曲线"><polyline id="cpu-line"/></svg></div>
          <div class="telemetry-item"><span>GPU 使用率</span><strong id="gpu-value">—</strong><svg viewBox="0 0 100 30" preserveAspectRatio="none" role="img" aria-label="GPU 使用率曲线"><polyline id="gpu-line"/></svg></div>
          <div class="telemetry-item"><span>内存使用量</span><strong id="ram-value">—</strong><svg viewBox="0 0 100 30" preserveAspectRatio="none" role="img" aria-label="内存使用率曲线"><polyline id="ram-line"/></svg></div>
          <div class="telemetry-item"><span>显存使用量</span><strong id="vram-value">—</strong><svg viewBox="0 0 100 30" preserveAspectRatio="none" role="img" aria-label="显存使用率曲线"><polyline id="vram-line"/></svg></div>
        </div><p>机器 SSH 就绪后约每秒采样一次；曲线保留最近 5 分钟。GPU 未就绪时暂不显示显存数据。</p></div>
        <div class="process"><div class="section-head"><div><div class="eyebrow">DEPLOYMENT</div><h3 id="progress-title">启动进度</h3></div><span id="progress-number">0%</span></div><div class="progress-track"><div id="progress-fill"></div></div><div id="progress-steps" class="steps"></div><div id="phase-message" class="phase-message">等待操作。点击“启动并连接”开始。</div><div id="model-progress" class="model-progress" hidden></div><details class="logbox"><summary>查看运行日志</summary><div id="log-lines"></div></details></div>
        <div class="local-card"><div class="section-head"><div><div class="eyebrow">COMFYUI CLIENT</div><h3>本地 ComfyUI</h3></div><span id="local-comfy-badge" class="local-badge">检查中</span></div><p id="local-comfy-status">正在检查安装状态…</p><div class="local-actions"><button id="install-comfy" type="button">一键安装 / 修复</button><button id="check-comfy" type="button">检查更新</button><button id="update-comfy" type="button" disabled>更新 ComfyUI</button></div><div id="local-comfy-progress" class="local-progress" role="status">安装在用户目录，工作流与输出文件不会随更新删除。</div></div>
      </section>
      <footer>Cloud GPU Studio <span>·</span> 临时云端存储会随机器删除 <span>·</span> 本地作品保留在 ComfyUI 输出目录</footer>
    </main>
  </div>
  <div id="confirm-comfy-overlay" class="confirm-overlay" hidden>
    <div class="confirm-box" role="dialog" aria-modal="true" aria-labelledby="confirm-comfy-title">
      <h4 id="confirm-comfy-title">停止本地 ComfyUI 并更新？</h4>
      <p>本地 ComfyUI 正在运行（127.0.0.1:8188）。更新前会先停止它，正在生成的图片或视频会中断。更新成功后会自动重新启动。</p>
      <div class="confirm-actions"><button id="confirm-comfy-cancel" type="button">取消</button><button id="confirm-comfy-ok" class="primary" type="button">停止并更新</button></div>
    </div>
  </div>`;

type Page = 'home' | 'models' | 'machines' | 'comfy' | 'settings';
const pageCopy: Record<Page, { eyebrow: string; title: string; subtitle: string }> = {
  home: { eyebrow: 'YOUR CREATIVE WORKSPACE', title: '创作工作台', subtitle: '模型、算力和本地 ComfyUI，一眼掌握。' },
  models: { eyebrow: '01 / MODEL PLAN', title: '模型方案', subtitle: '先决定图片与视频模型，再保存部署方案。' },
  machines: { eyebrow: '02 / CLOUD GPU', title: '云端机器', subtitle: '筛选显卡、启动实例，并查看部署进度与实时资源。' },
  comfy: { eyebrow: '03 / LOCAL CLIENT', title: '本地 ComfyUI', subtitle: '编辑工作流、管理本地安装与更新。' },
  settings: { eyebrow: '04 / ACCOUNT', title: '账户设置', subtitle: '管理云平台凭证；密钥只保存在这台电脑上。' },
};
const dashboard = document.querySelector<HTMLElement>('.dashboard')!;
const pages = {} as Record<Page, HTMLElement>;
for (const name of Object.keys(pageCopy) as Page[]) {
  const section = document.createElement('section');
  section.className = `page page-${name}`;
  section.dataset.page = name;
  section.hidden = name !== 'home';
  dashboard.append(section);
  pages[name] = section;
}
pages.home.innerHTML = `
  <div class="welcome-card">
    <div class="welcome-copy"><div class="welcome-kicker"><span class="kicker-dot"></span> CLOUD GPU STUDIO / OVERVIEW</div>
      <h2>灵感在本地，<br><em>算力在云端。</em></h2>
      <p>选好模型与显卡，再打开熟悉的 ComfyUI 工作流。每一步都在自己的位置，创作时只关注作品。</p>
      <div class="welcome-actions"><button class="welcome-primary" data-go="models" type="button">配置模型 <span>↗</span></button><button class="welcome-secondary" data-go="machines" type="button">查看云端机器 <span>→</span></button></div>
    </div>
    <div class="welcome-visual" aria-hidden="true"><div class="visual-ring ring-outer"></div><div class="visual-ring ring-inner"></div><img class="visual-logo" src="/brand-mark.svg" alt=""><div class="visual-caption">CREATE · CONNECT · RUN</div></div>
  </div>
  <div class="home-heading"><div><div class="eyebrow">AT A GLANCE</div><h3>当前工作区</h3></div><span id="home-provider">正在读取配置</span></div>
  <div class="home-tiles"><button data-go="models" type="button" class="home-tile"><span class="tile-icon violet">✳</span><small>模型方案</small><strong id="home-model">读取中</strong><span>查看与调整 <b>↗</b></span></button><button data-go="machines" type="button" class="home-tile"><span class="tile-icon blue">▧</span><small>云端机器</small><strong id="home-machine">检查中</strong><span>筛选显卡与报价 <b>↗</b></span></button><button data-go="comfy" type="button" class="home-tile"><span class="tile-icon mint">⌘</span><small>本地 ComfyUI</small><strong id="home-comfy">检查中</strong><span>打开或管理 <b>↗</b></span></button></div>
  <div class="home-heading home-heading-lower"><div><div class="eyebrow">LIVE STATUS</div><h3>运行概况</h3></div><button data-go="machines" type="button">查看部署详情 →</button></div>
  <div class="home-activity"><div><span class="activity-mark">↗</span><div><strong id="home-activity-title">等待操作</strong><p id="home-activity-message">选择模型和显卡后即可启动云端机器。</p></div></div><div class="activity-progress"><span id="home-progress-label">0%</span><div><i id="home-progress-fill"></i></div></div></div>
`;
pages.home.append(document.querySelector('.metrics')!);
pages.models.append(document.querySelector('.config-card')!);
const settingsCard = document.createElement('div');
settingsCard.className = 'settings-card';
settingsCard.innerHTML = `<div class="section-head"><div><div class="eyebrow">PRIVATE CREDENTIALS</div><h3>平台 API Key</h3></div></div>
  <p>RunPod 和 Vast.ai 的密钥可以分别配置。部署时使用“模型方案”中选定的平台；已保存的密钥不会显示在界面上。</p>
  <div class="provider-keys">
    <div class="provider-key-card"><div class="provider-key-heading"><strong>RunPod</strong><span id="key-badge-runpod">检查中</span></div><div class="key-row"><label>RunPod API Key<input id="api-key-runpod" type="password" autocomplete="off" placeholder="输入新的 RunPod API Key" spellcheck="false"></label><button id="save-key-runpod" type="button">保存</button><small id="key-state-runpod">正在检查密钥状态…</small></div></div>
    <div class="provider-key-card"><div class="provider-key-heading"><strong>Vast.ai</strong><span id="key-badge-vast">检查中</span></div><div class="key-row"><label>Vast.ai API Key<input id="api-key-vast" type="password" autocomplete="off" placeholder="输入新的 Vast.ai API Key" spellcheck="false"></label><button id="save-key-vast" type="button">保存</button><small id="key-state-vast">正在检查密钥状态…</small></div></div>
  </div>`;
pages.settings.append(settingsCard);
const updateCard = document.createElement('div');
updateCard.className = 'settings-card app-update-card';
updateCard.innerHTML = `<div class="section-head"><div><div class="eyebrow">APP UPDATES</div><h3>应用更新</h3></div></div><p id="app-update-status">正在检查应用版本…</p><div class="app-update-actions"><button id="check-app-update" type="button">检查应用更新</button><button id="install-app-update" type="button" disabled>下载并安装</button></div>`;
pages.settings.append(updateCard);
pages.machines.append(document.querySelector('.offer-card')!, document.querySelector('.hero')!, document.querySelector('.process')!, document.querySelector('.telemetry')!);
const localCard = document.querySelector('.local-card')!;
const localSession = document.createElement('div');
localSession.className = 'local-session';
localSession.append(document.querySelector('#open-comfy')!, document.querySelector('#stop-comfy')!);
localCard.insertBefore(localSession, localCard.querySelector('.local-actions'));
pages.comfy.append(localCard);
let activePage: Page = 'home';
function showPage(page: Page) {
  activePage = page;
  for (const name of Object.keys(pages) as Page[]) pages[name].hidden = name !== page;
  document.querySelectorAll<HTMLButtonElement>('[data-nav]').forEach(button => {
    const active = button.dataset.nav === page;
    button.classList.toggle('active', active);
    if (active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
  });
  document.querySelector<HTMLElement>('#page-eyebrow')!.textContent = pageCopy[page].eyebrow;
  document.querySelector<HTMLElement>('#page-title')!.textContent = pageCopy[page].title;
  document.querySelector<HTMLElement>('#page-subtitle')!.textContent = pageCopy[page].subtitle;
  document.querySelector<HTMLElement>('.topbar')!.classList.toggle('topbar-home', page === 'home');
  document.querySelector<HTMLElement>('.main')!.scrollTop = 0;
}
document.querySelectorAll<HTMLButtonElement>('[data-nav], [data-go]').forEach(button => {
  button.addEventListener('click', () => showPage((button.dataset.nav || button.dataset.go) as Page));
});
showPage('home');
const languageSelect = document.querySelector<HTMLSelectElement>('#ui-language')!;
languageSelect.value = currentLanguage();
languageSelect.addEventListener('change', () => setLanguage(languageSelect.value as 'zh-CN' | 'en-US', app));
startI18n(app);

let availableAppUpdate: Update | null = null;
const appUpdateStatus = document.querySelector<HTMLElement>('#app-update-status')!;
const installAppUpdate = document.querySelector<HTMLButtonElement>('#install-app-update')!;
async function checkAppUpdate() {
  const button = document.querySelector<HTMLButtonElement>('#check-app-update')!;
  const tauriInternals = (window as unknown as { __TAURI_INTERNALS__?: { invoke?: unknown } }).__TAURI_INTERNALS__;
  if (typeof tauriInternals?.invoke !== 'function') {
    appUpdateStatus.textContent = '应用更新仅在桌面版中可用。';
    button.disabled = true;
    return;
  }
  button.disabled = true;
  appUpdateStatus.textContent = '正在检查应用版本…';
  try {
    availableAppUpdate = await check();
    appUpdateStatus.textContent = availableAppUpdate ? `发现新版本 ${availableAppUpdate.version}，可下载安装。` : '当前已是最新应用版本。';
    installAppUpdate.disabled = !availableAppUpdate;
  } catch (error) {
    const message = String(error);
    appUpdateStatus.textContent = /404|not found/i.test(message) ? '尚无已发布版本；发布首个 Release 后可检查更新。' : `应用更新检查失败：${message}`;
  } finally { button.disabled = false; }
}
document.querySelector<HTMLButtonElement>('#check-app-update')!.addEventListener('click', () => { void checkAppUpdate(); });
installAppUpdate.addEventListener('click', async () => {
  if (!availableAppUpdate || operating) {
    appUpdateStatus.textContent = operating ? '请等待当前部署操作完成后再更新应用。' : '请先检查应用更新。';
    return;
  }
  installAppUpdate.disabled = true;
  try {
    appUpdateStatus.textContent = '正在下载应用更新…';
    await availableAppUpdate.downloadAndInstall(event => {
      if (event.event === 'Started') appUpdateStatus.textContent = '正在下载应用更新…';
      else if (event.event === 'Finished') appUpdateStatus.textContent = '下载完成，正在安装…';
    });
    appUpdateStatus.textContent = '更新已安装，正在重启应用…';
    await relaunch();
  } catch (error) {
    appUpdateStatus.textContent = `应用更新失败：${String(error)}`;
    installAppUpdate.disabled = false;
  }
});
void checkAppUpdate();

const el = <T extends Element>(id: string) => document.getElementById(id) as unknown as T;
const launch = el<HTMLButtonElement>('launch');
const remove = el<HTMLButtonElement>('delete');
const cancelButton = el<HTMLButtonElement>('cancel-launch');
const log = el<HTMLDivElement>('log-lines');
const providerSelect = el<HTMLSelectElement>('provider');
const imageSelect = el<HTMLSelectElement>('image-model');
const videoSelect = el<HTMLSelectElement>('video-model');
const modelUrl = el<HTMLInputElement>('model-url');
let latestStatus: Status | null = null;
let savedSettings: Settings | null = null;
let inspectedModel: ModelFile | null = null;
let configDirty = false;
let operating = false;
let currentPhase = '';
let lastError = '';
let lastPercent = 0;
let lastModelPercent: number | null = null;
let lastStageIndex = 0;
let nativeOpened = false;
let refreshing = false;
let progressMode: 'start' | 'cancel' | 'delete' = 'start';
let packDirty = false;
let localComfy: LocalComfy | null = null;
let localBusy = false;
let localOpening = false;
let restartComfyAfterUpdate = false;
let offers: GpuOffer[] = [];
let selectedOffer: GpuOffer | null = null;
let queryingOffers = false;
let ref2vaBusy = false;
let offerQueryRevision = 0;
let metricsPolling = false;
let metricsPodId: string | null = null;
const metricsHistory: Record<string, number[]> = { cpu: [], gpu: [], ram: [], vram: [] };

const startSteps = ['创建机器', '启动 GPU', '安装与下载', '校验与启动', '连接隧道', '本地界面'];
const deleteSteps = ['提交删除', '释放云端资源', '确认完成'];
const cancelSteps = ['提交取消', '停止部署', '机器保留'];

function renderHome() {
  const provider = savedSettings?.provider === 'vast' ? 'Vast.ai' : 'RunPod';
  el<HTMLElement>('home-provider').textContent = savedSettings ? `${provider} · ${savedSettings.video_mode === 'ref2va' ? '多参考模式' : '首帧模式'}` : '正在读取配置';
  const image = { qwen: 'Qwen Image 2.1', 'local-qwen': '自选 Qwen', checkpoint: 'HF Checkpoint', none: '无图片模型' }[savedSettings?.image_model || 'none'];
  const video = { h3: 'MiniMax H3', 'local-h3': '自选 H3', none: '无视频模型' }[savedSettings?.video_model || 'none'];
  el<HTMLElement>('home-model').textContent = savedSettings ? `${image} + ${video}` : '读取中';
  el<HTMLElement>('home-machine').textContent = latestStatus?.podId ? '运行中' : '未启动';
  const installed = Boolean(localComfy?.installed && localComfy.python_ready && localComfy.bridge_ready);
  el<HTMLElement>('home-comfy').textContent = installed ? (latestStatus?.localReady ? '正在运行' : '已安装') : localComfy ? '需要安装' : '检查中';
}

function renderSteps(labels: string[]) {
  const container = el<HTMLDivElement>('progress-steps');
  container.replaceChildren(...labels.map(label => {
    const span = document.createElement('span');
    span.textContent = label;
    return span;
  }));
  container.style.gridTemplateColumns = `repeat(${labels.length}, 1fr)`;
}

renderSteps(startSteps);

function appendLog(message: string, level = 'info') {
  const row = document.createElement('div');
  row.className = `log-line ${level}`;
  const time = document.createElement('time');
  time.textContent = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  const content = document.createElement('span');
  content.textContent = message;
  row.append(time, content);
  log.append(row);
  while (log.children.length > 180) log.firstChild?.remove();
  log.scrollTop = log.scrollHeight;
}

function setProgress(progress: Progress) {
  const previousPhase = currentPhase;
  if (progress.phase === 'deleting' || progress.phase === 'deleted') progressMode = 'delete';
  else if (progress.phase === 'cancelling' || progress.phase === 'cancelled') progressMode = 'cancel';
  else if (progress.phase === 'creating') progressMode = 'start';
  if (progress.phase !== 'working') currentPhase = progress.phase;
  el<HTMLElement>('progress-title').textContent = progressMode === 'delete' ? '删除进度' : progressMode === 'cancel' ? '取消进度' : '启动进度';
  const labels = progressMode === 'delete' ? deleteSteps : progressMode === 'cancel' ? cancelSteps : startSteps;
  if (el<HTMLDivElement>('progress-steps').children.length !== labels.length) renderSteps(labels);
  const percent = progress.phase === 'error' ? lastPercent : Math.max(lastPercent, progress.percent);
  lastPercent = percent;
  el<HTMLDivElement>('progress-fill').style.width = `${percent}%`;
  el<HTMLSpanElement>('progress-number').textContent = `${percent}%`;
  const message = el<HTMLDivElement>('phase-message');
  message.textContent = progress.message;
  message.classList.toggle('error', progress.level === 'error');
  const model = el<HTMLDivElement>('model-progress');
  if (progress.modelPercent !== null) lastModelPercent = progress.modelPercent;
  if (['cloud-ready', 'tunnel', 'local', 'ready', 'deleting', 'deleted', 'cancelling', 'cancelled'].includes(progress.phase)) lastModelPercent = null;
  model.hidden = lastModelPercent === null;
  if (lastModelPercent !== null) model.textContent = `模型数据下载：${lastModelPercent}%`;
  const order: Record<string, number> = { creating: 0, booting: 1, installing: 2, downloading: 2,
    verifying: 3, 'cloud-ready': 3, tunnel: 4, local: 5, ready: 6 };
  let index = progressMode === 'delete' ? (progress.phase === 'deleted' ? 2 : 1)
    : progressMode === 'cancel' ? (progress.phase === 'cancelled' ? 2 : 1)
    : (order[progress.phase] ?? order[previousPhase] ?? 0);
  if (progressMode === 'start') { lastStageIndex = Math.max(lastStageIndex, index); index = lastStageIndex; }
  document.querySelectorAll<HTMLElement>('#progress-steps span').forEach((step, i) => {
    step.classList.toggle('done', ['ready', 'deleted', 'cancelled'].includes(progress.phase) || (index >= 0 && i < index));
    step.classList.toggle('current', index === i && !['ready', 'deleted', 'cancelled', 'error'].includes(progress.phase));
  });
  if (progress.level === 'error') lastError = progress.message;
  el<HTMLElement>('home-activity-title').textContent = progress.level === 'error' ? '操作遇到问题' : progressMode === 'delete' ? '正在删除云端机器' : progressMode === 'cancel' ? '正在取消部署' : progress.phase === 'ready' ? '云端机器已就绪' : '正在准备云端机器';
  el<HTMLElement>('home-activity-message').textContent = progress.message;
  el<HTMLElement>('home-progress-label').textContent = `${percent}%`;
  el<HTMLElement>('home-progress-fill').style.width = `${percent}%`;
  appendLog(progress.message, progress.level);
}

function updateControls() {
  launch.disabled = operating || Boolean(latestStatus?.busy) || !savedSettings?.keys[savedSettings.provider] || configDirty || (!latestStatus?.podId && !selectedOffer);
  const canInterruptLaunch = (!operating && Boolean(latestStatus?.launching)) || (operating && progressMode === 'start');
  cancelButton.hidden = !canInterruptLaunch;
  cancelButton.disabled = !canInterruptLaunch;
  remove.disabled = canInterruptLaunch ? false : operating || Boolean(latestStatus?.busy) || !latestStatus?.podId;
  launch.innerHTML = latestStatus?.podId ? '连接已有机器 <span>↗</span>' : '启动并连接 <span>↗</span>';
  const locked = operating || Boolean(latestStatus?.busy) || Boolean(latestStatus?.podId);
  el<HTMLButtonElement>('query-offers').disabled = locked || queryingOffers || configDirty || !savedSettings?.keys[savedSettings.provider];
  el<HTMLInputElement>('max-price').disabled = locked || queryingOffers;
  el<HTMLSelectElement>('gpu-filter').disabled = locked || queryingOffers || offers.length === 0;
  document.querySelectorAll<HTMLButtonElement>('.offer-option').forEach(button => { button.disabled = locked || queryingOffers; });
  for (const id of ['provider', 'image-model', 'video-model', 'model-url', 'inspect-model', 'save-config']) {
    (el<HTMLInputElement | HTMLButtonElement | HTMLSelectElement>(id)).disabled = locked;
  }
  for (const provider of ['runpod', 'vast']) {
    el<HTMLInputElement>(`api-key-${provider}`).disabled = locked;
    el<HTMLButtonElement>(`save-key-${provider}`).disabled = locked;
  }
  el<HTMLButtonElement>('save-pack').disabled = locked;
  document.querySelectorAll<HTMLInputElement>('[data-pack-kind]').forEach(input => { input.disabled = locked; });
  const localReadyToOpen = Boolean(latestStatus?.localReady) || Boolean(localComfy?.installed && localComfy.python_ready && localComfy.bridge_ready);
  const openButton = el<HTMLButtonElement>('open-comfy');
  openButton.disabled = localOpening || localBusy || !localReadyToOpen;
  openButton.textContent = localOpening ? '正在打开 ComfyUI…' : '打开 ComfyUI ↗';
  const localLocked = localBusy || localOpening || operating || Boolean(latestStatus?.busy);
  el<HTMLButtonElement>('install-comfy').disabled = localLocked;
  el<HTMLButtonElement>('check-comfy').disabled = localLocked || !localComfy?.git_ready;
  el<HTMLButtonElement>('stop-comfy').disabled = localLocked || !latestStatus?.localReady;
  // 本地 ComfyUI 正在运行（localReady）时也允许更新：更新脚本会拉取代码并安装依赖，
  // 完成后提示重启即可；否则用户打开着 ComfyUI 时就永远点不了更新按钮。
  el<HTMLButtonElement>('update-comfy').disabled = localLocked || !localComfy?.update_available;
  const modeLocked = operating || ref2vaBusy || Boolean(latestStatus?.busy) || configDirty || savedSettings?.video_model === 'none';
  el<HTMLButtonElement>('download-ref2va').disabled = modeLocked || !latestStatus?.podId || Boolean(savedSettings?.ref2va_ready);
  el<HTMLButtonElement>('switch-ref2va').disabled = modeLocked || !savedSettings?.ref2va_ready || savedSettings?.video_mode === 'ref2va';
  el<HTMLButtonElement>('download-fl2va').disabled = modeLocked || !latestStatus?.podId || Boolean(savedSettings?.fl2va_ready);
  el<HTMLButtonElement>('switch-fl2va').disabled = modeLocked || !savedSettings?.fl2va_ready || savedSettings?.video_mode === 'fl2va';
}

function renderLocalComfyBadge() {
  const ready = Boolean(localComfy?.installed && localComfy.python_ready && localComfy.bridge_ready);
  const badge = el<HTMLElement>('local-comfy-badge');
  if (!localComfy) { badge.textContent = '检查中'; renderHome(); return; }
  badge.textContent = !ready ? (localComfy.installed ? '需要修复' : '未安装')
    : latestStatus?.localReady ? '已就绪 · 运行中' : '已就绪';
  renderHome();
}

function renderLocalComfy(value: LocalComfy) {
  localComfy = value;
  renderLocalComfyBadge();
  el<HTMLElement>('local-comfy-status').textContent = `${value.path} · ${value.version ? `版本 ${value.version}` : '未检测到版本'}${value.update_available === true ? ' · 有可用更新' : value.update_available === false ? ' · 已是最新' : ''}`;
  if (value.error) el<HTMLElement>('local-comfy-progress').textContent = `检查更新失败：${value.error}`;
  updateControls();
}

async function refreshLocalComfy() {
  try { renderLocalComfy(await invoke<LocalComfy>('get_local_comfy_status')); }
  catch (error) { el<HTMLElement>('local-comfy-progress').textContent = `读取安装状态失败：${String(error)}`; }
}

async function stopLocalComfyProcess() {
  await invoke('stop_local_comfy');
  nativeOpened = false;
  await refresh();
}

function confirmComfyStop(): Promise<boolean> {
  return new Promise(resolve => {
    const overlay = el<HTMLDivElement>('confirm-comfy-overlay');
    const okButton = el<HTMLButtonElement>('confirm-comfy-ok');
    const cancelButton = el<HTMLButtonElement>('confirm-comfy-cancel');
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') finish(false); };
    function finish(value: boolean) {
      overlay.hidden = true;
      overlay.onclick = null;
      okButton.onclick = null;
      cancelButton.onclick = null;
      document.removeEventListener('keydown', onKey);
      resolve(value);
    }
    okButton.onclick = () => finish(true);
    cancelButton.onclick = () => finish(false);
    overlay.onclick = event => { if (event.target === overlay) finish(false); };
    document.addEventListener('keydown', onKey);
    overlay.hidden = false;
    okButton.focus();
  });
}

function modelUrlFor(file: ModelFile): string {
  return `https://huggingface.co/${file.repo}/blob/${file.revision}/${file.filename}`;
}

function renderPack(settings: Settings) {
  const box = el<HTMLDivElement>('pack-summary');
  box.replaceChildren();
  if (!settings.local_pack.ready) {
    box.textContent = `本地组件包尚未就绪：${settings.local_pack.error}`;
    document.querySelectorAll<HTMLInputElement>('[data-pack-kind]').forEach(input => { input.value = ''; });
    return;
  }
  document.querySelectorAll<HTMLInputElement>('[data-pack-kind]').forEach(input => {
    const kind = input.dataset.packKind as 'qwen' | 'h3';
    input.value = settings.local_pack.ready ? settings.local_pack.urls[kind]?.[input.dataset.packRole || ''] || '' : '';
  });
  for (const [title, components] of [['图片', settings.local_pack.image], ['视频', settings.local_pack.video]] as const) {
    const section = document.createElement('div');
    const heading = document.createElement('strong');
    heading.textContent = `${title}组件`;
    section.append(heading);
    for (const [role, filename] of Object.entries(components)) {
      const row = document.createElement('div');
      row.textContent = `${role}: ${filename}`;
      section.append(row);
    }
    box.append(section);
  }
  const size = document.createElement('small');
  size.textContent = `完整组件包约 ${settings.local_pack.size_gb} GB；实际下载量按所选图片和视频模型计算。`;
  box.append(size);
}

function renderSettings(settings: Settings) {
  clearOffers('配置已加载，请查询当前平台报价。');
  savedSettings = settings;
  packDirty = false;
  providerSelect.value = settings.provider;
  imageSelect.value = settings.image_model;
  videoSelect.value = settings.video_model;
  el<HTMLElement>('mode-state').textContent = settings.video_mode === 'ref2va'
    ? '多参考 Ref2VA 已启用' : '首帧 / 尾帧 FL2VA 已启用';
  if (!ref2vaBusy) el<HTMLElement>('mode-progress').textContent = settings.video_mode === 'ref2va'
    ? `优先使用 Ref2VA，多参考图已就绪。${settings.fl2va_ready ? '首帧模式也已下载。' : '首帧模式可按需下载。'}`
    : `首帧 FL2VA 已启用。${settings.ref2va_ready ? '多参考模式也已下载。' : '多参考模式可按需下载。'}`;
  inspectedModel = settings.custom_model;
  modelUrl.value = settings.custom_model ? modelUrlFor(settings.custom_model) : '';
  configDirty = false;
  el<HTMLElement>('custom-row').hidden = settings.image_model !== 'checkpoint';
  renderPack(settings);
  for (const provider of ['runpod', 'vast'] as const) {
    const ready = settings.keys[provider];
    el<HTMLElement>(`key-badge-${provider}`).textContent = ready ? '已配置' : '未配置';
    el<HTMLElement>(`key-badge-${provider}`).classList.toggle('ready', ready);
    el<HTMLElement>(`key-state-${provider}`).textContent = ready
      ? '密钥已保存在本机；输入新密钥可替换。' : '尚未配置，请输入并保存。';
  }
  el<HTMLElement>('config-state').textContent = '已保存';
  el<HTMLElement>('model-info').textContent = settings.custom_model
    ? `${settings.custom_model.filename} · ${(settings.custom_model.size / 1e9).toFixed(1)} GB · 已锁定版本`
    : '仅支持单文件 SD/SDXL checkpoint；视频模型请使用兼容的组件包。';
  renderHome();
  updateControls();
}

function markDirty() {
  clearOffers('请先保存配置，再查询当前平台报价。');
  configDirty = true;
  el<HTMLElement>('config-state').textContent = '未保存';
  el<HTMLElement>('config-message').textContent = '请先保存配置，再启动机器。';
  el<HTMLElement>('custom-row').hidden = imageSelect.value !== 'checkpoint';
  el<HTMLElement>('home-provider').textContent = '模型方案有未保存更改';
  updateControls();
}

function clearOffers(message: string) {
  offerQueryRevision += 1;
  offers = [];
  selectedOffer = null;
  el<HTMLElement>('offer-count').textContent = '尚未查询';
  el<HTMLElement>('offer-message').textContent = message;
  el<HTMLSelectElement>('gpu-filter').replaceChildren(new Option('全部兼容型号', ''));
  el<HTMLDivElement>('gpu-offers').replaceChildren();
  updateControls();
}

function renderOffers() {
  const filter = el<HTMLSelectElement>('gpu-filter').value;
  const visible = offers.filter(offer => !filter || offer.gpu === filter);
  el<HTMLElement>('offer-count').textContent = `${visible.length} 台可选`;
  const list = el<HTMLDivElement>('gpu-offers');
  list.replaceChildren(...visible.map(offer => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `offer-option${selectedOffer?.id === offer.id ? ' selected' : ''}`;
    const heading = document.createElement('strong');
    heading.textContent = offer.gpu;
    const price = document.createElement('span');
    price.className = 'offer-price';
    price.textContent = `$${offer.price.toFixed(3)}/小时`;
    const details = document.createElement('small');
    details.textContent = `${offer.location} · ${offer.vramGb} GB 显存${offer.reliability === null ? '' : ` · 可靠度 ${offer.reliability}%`}`;
    button.append(heading, price, details);
    button.disabled = operating || Boolean(latestStatus?.busy) || Boolean(latestStatus?.podId);
    button.addEventListener('click', () => {
      selectedOffer = offer;
      el<HTMLElement>('offer-message').textContent = `已选择 ${offer.gpu}，报价 $${offer.price.toFixed(3)}/小时。启动前会核对库存与价格上限。`;
      renderOffers();
      updateControls();
    });
    return button;
  }));
  updateControls();
}

async function fetchOffers() {
  const rawPrice = el<HTMLInputElement>('max-price').value.trim();
  const maxPrice = rawPrice ? Number(rawPrice) : null;
  if (maxPrice !== null && (!Number.isFinite(maxPrice) || maxPrice <= 0)) {
    el<HTMLElement>('offer-message').textContent = '价格筛选值必须是高于 $0 的有限数字；留空表示不限。';
    return;
  }
  queryingOffers = true;
  const revision = ++offerQueryRevision;
  selectedOffer = null;
  el<HTMLElement>('offer-count').textContent = '查询中';
  el<HTMLElement>('offer-message').textContent = `正在查询 ${savedSettings?.provider === 'vast' ? 'Vast.ai' : 'RunPod'} 的实时库存和价格…`;
  el<HTMLDivElement>('gpu-offers').replaceChildren();
  updateControls();
  try {
    const result = await invoke<GpuOffer[]>('get_gpu_offers', { maxPrice });
    if (revision !== offerQueryRevision) return;
    offers = result;
    const filter = el<HTMLSelectElement>('gpu-filter');
    filter.replaceChildren(new Option('全部兼容型号', ''), ...Array.from(new Set(offers.map(offer => offer.gpu))).sort().map(name => new Option(name, name)));
    el<HTMLElement>('offer-message').textContent = offers.length ? '请选择一台机器。报价可能变化，启动前会重新核对。' : maxPrice === null ? '当前没有符合部署要求的机器；可以稍后重试。' : '当前价格上限内没有符合部署要求的机器；可以提高上限或稍后重试。';
    renderOffers();
  } catch (error) {
    if (revision === offerQueryRevision) clearOffers(`报价查询失败：${String(error)}`);
  } finally {
    queryingOffers = false;
    updateControls();
  }
}

async function loadSettings() {
  try { renderSettings(await invoke<Settings>('get_settings')); }
  catch (error) { el<HTMLElement>('config-message').textContent = `配置读取失败：${String(error)}`; }
}

function resetTelemetry(podId: string | null) {
  metricsPodId = podId;
  for (const series of Object.values(metricsHistory)) series.length = 0;
  for (const key of ['cpu', 'gpu', 'ram', 'vram']) {
    el<HTMLElement>(`${key}-value`).textContent = '—';
    el<SVGPolylineElement>(`${key}-line`).setAttribute('points', '');
  }
  el<HTMLElement>('telemetry-status').textContent = podId ? '等待远程主机…' : '云端未启动';
}

function addTelemetryPoint(key: string, percent: number | null | undefined) {
  if (percent === null || percent === undefined || !Number.isFinite(percent)) return;
  const series = metricsHistory[key];
  series.push(Math.max(0, Math.min(100, percent)));
  if (series.length > 300) series.shift();
  const points = series.map((value, index) => `${series.length === 1 ? 50 : index * 100 / (series.length - 1)},${30 - value * .28}`).join(' ');
  el<SVGPolylineElement>(`${key}-line`).setAttribute('points', points);
}

async function pollMetrics() {
  const podId = latestStatus?.podId;
  if (!podId || metricsPolling) return;
  metricsPolling = true;
  try {
    const value = await invoke<HostMetrics>('get_host_metrics');
    if (metricsPodId !== podId) return;
    if (!value.online) {
      el<HTMLElement>('telemetry-status').textContent = value.message || '等待远程指标…';
      return;
    }
    el<HTMLElement>('telemetry-status').textContent = `最近采样 ${new Date().toLocaleTimeString('zh-CN', { hour12: false })}`;
    if (value.cpuPercent != null) {
      el<HTMLElement>('cpu-value').textContent = `${value.cpuPercent.toFixed(1)}%`;
      addTelemetryPoint('cpu', value.cpuPercent);
    }
    if (value.gpuPercent != null) {
      el<HTMLElement>('gpu-value').textContent = `${value.gpuPercent.toFixed(1)}%`;
      addTelemetryPoint('gpu', value.gpuPercent);
    }
    if (value.ramUsedGb != null && value.ramTotalGb) {
      el<HTMLElement>('ram-value').textContent = `${value.ramUsedGb.toFixed(1)} / ${value.ramTotalGb.toFixed(1)} GB`;
      addTelemetryPoint('ram', value.ramUsedGb / value.ramTotalGb * 100);
    }
    if (value.vramUsedGb != null && value.vramTotalGb) {
      el<HTMLElement>('vram-value').textContent = `${value.vramUsedGb.toFixed(1)} / ${value.vramTotalGb.toFixed(1)} GB`;
      addTelemetryPoint('vram', value.vramUsedGb / value.vramTotalGb * 100);
    }
  } catch (error) {
    if (metricsPodId === podId) el<HTMLElement>('telemetry-status').textContent = `读取失败：${String(error)}`;
  } finally { metricsPolling = false; }
}

function renderStatus(s: Status) {
  latestStatus = s;
  renderLocalComfyBadge();
  if (s.podId !== metricsPodId) {
    resetTelemetry(s.podId);
    if (s.podId) void pollMetrics();
  }
  el<HTMLElement>('pod-value').textContent = s.podId ? '运行中' : '未启动';
  el<HTMLElement>('pod-detail').textContent = s.podId ? `Pod ${s.podId}` : '没有运行中的 Pod';
  if (s.provider === 'vast' && s.podId) el<HTMLElement>('pod-detail').textContent = `Vast.ai 实例 ${s.podId}`;
  el<HTMLElement>('price-value').textContent = s.costPerHour === null ? '—' : `$${s.costPerHour.toFixed(2)}`;
  el<HTMLElement>('balance-value').textContent = s.balance === null ? '—' : `$${s.balance.toFixed(2)}`;
  const connected = s.localReady && s.tunnelReady && Boolean(s.podId);
  el<HTMLElement>('connection-value').textContent = connected ? '已连接' : s.podId ? '待连接' : '离线';
  el<HTMLElement>('connection-detail').textContent = connected ? 'SSH 隧道与本地界面已就绪' : '本地端口 8188 / 8189';
  const badge = el<HTMLElement>('top-status');
  badge.innerHTML = `<span class="pulse"></span> ${connected ? '可以创作' : s.podId ? '云端已启动' : '云端离线'}`;
  badge.classList.toggle('online', connected);
  if (connected && !nativeOpened) {
    nativeOpened = true;
    void invoke('open_comfy_window').catch(error => { nativeOpened = false; appendLog(`打开 ComfyUI 窗口失败：${String(error)}`, 'error'); });
  }
  if (!connected) nativeOpened = false;
  if (s.oldVolumeBilled) appendLog('检测到旧版网络存储仍在计费，请检查 RunPod 控制台。', 'error');
  renderHome();
  updateControls();
}

async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const status = await invoke<Status>('get_status');
    renderStatus(status);
    if (lastError && !operating) el<HTMLElement>('phase-message').textContent = lastError;
  } catch (error) {
    el<HTMLElement>('top-status').textContent = '状态读取失败';
    appendLog(`状态读取失败：${String(error)}`, 'error');
  } finally {
    refreshing = false;
  }
}

launch.addEventListener('click', async () => {
  if (!latestStatus?.podId && !selectedOffer) return;
  const offerId = latestStatus?.podId ? null : selectedOffer?.id;
  const rawPrice = el<HTMLInputElement>('max-price').value.trim();
  const maxPrice = rawPrice ? Number(rawPrice) : selectedOffer?.price ?? null;
  operating = true; progressMode = 'start'; lastError = ''; lastPercent = 0; lastModelPercent = null; lastStageIndex = 0; updateControls();
  setProgress({ phase: 'creating', message: '正在准备启动…', percent: 2, modelPercent: null, level: 'info' });
  try { await invoke('launch', { offerId, maxPrice }); }
  catch (error) { operating = false; setProgress({ phase: 'error', message: String(error), percent: 0, modelPercent: null, level: 'error' }); updateControls(); }
});

el<HTMLButtonElement>('query-offers').addEventListener('click', () => { void fetchOffers(); });
el<HTMLInputElement>('max-price').addEventListener('input', () => clearOffers('价格上限已更改，请重新查询报价。'));
el<HTMLSelectElement>('gpu-filter').addEventListener('change', () => {
  selectedOffer = null;
  el<HTMLElement>('offer-message').textContent = '请选择筛选结果中的机器。';
  renderOffers();
});

remove.addEventListener('click', async () => {
  const interruptedLaunch = Boolean(latestStatus?.launching) || (progressMode === 'start' && operating);
  operating = true; progressMode = 'delete'; lastError = ''; lastPercent = 0; lastModelPercent = null; updateControls();
  setProgress({ phase: 'deleting', message: interruptedLaunch ? '正在停止部署并删除机器…' : '正在提交删除请求…', percent: 5, modelPercent: null, level: 'info' });
  try { await invoke('delete_cloud'); }
  catch (error) { operating = false; if (interruptedLaunch) progressMode = 'start'; setProgress({ phase: 'error', message: String(error), percent: 0, modelPercent: null, level: 'error' }); updateControls(); }
});

cancelButton.addEventListener('click', async () => {
  operating = true; progressMode = 'cancel'; lastError = ''; lastPercent = 0; lastModelPercent = null; updateControls();
  setProgress({ phase: 'cancelling', message: '正在停止部署；云端机器会保留并继续计费。', percent: 5, modelPercent: null, level: 'info' });
  try { await invoke('cancel_launch'); }
  catch (error) { operating = false; progressMode = 'start'; setProgress({ phase: 'error', message: String(error), percent: 0, modelPercent: null, level: 'error' }); updateControls(); }
});

el<HTMLButtonElement>('open-comfy').addEventListener('click', async () => {
  localOpening = true;
  updateControls();
  el<HTMLElement>('local-comfy-progress').textContent = '正在启动本地 ComfyUI，无需等待云端 GPU…';
  try {
    await invoke('open_comfy_window');
    nativeOpened = true;
    el<HTMLElement>('local-comfy-progress').textContent = '本地 ComfyUI 已打开；云端连接完成前可以编辑工作流。';
    await refresh();
  } catch (error) {
    const message = `打开 ComfyUI 窗口失败：${String(error)}`;
    el<HTMLElement>('local-comfy-progress').textContent = message;
    appendLog(message, 'error');
  } finally { localOpening = false; updateControls(); }
});

el<HTMLButtonElement>('stop-comfy').addEventListener('click', async () => {
  localBusy = true; updateControls();
  el<HTMLElement>('local-comfy-progress').textContent = '正在关闭本地 ComfyUI…';
  try {
    await stopLocalComfyProcess();
    el<HTMLElement>('local-comfy-progress').textContent = '本地 ComfyUI 已关闭，需要时可点击“打开 ComfyUI”重新启动。';
  } catch (error) {
    el<HTMLElement>('local-comfy-progress').textContent = `关闭本地 ComfyUI 失败：${String(error)}`;
  } finally { localBusy = false; updateControls(); }
});

el<HTMLButtonElement>('install-comfy').addEventListener('click', async () => {
  localBusy = true; updateControls();
  el<HTMLElement>('local-comfy-progress').textContent = '准备安装本地 ComfyUI…';
  try { await invoke('manage_local_comfy', { action: 'install' }); }
  catch (error) { localBusy = false; el<HTMLElement>('local-comfy-progress').textContent = `安装失败：${String(error)}`; updateControls(); }
});

el<HTMLButtonElement>('check-comfy').addEventListener('click', async () => {
  localBusy = true; updateControls();
  el<HTMLElement>('local-comfy-progress').textContent = '正在检查官方仓库更新…';
  try { renderLocalComfy(await invoke<LocalComfy>('check_local_comfy_update')); if (!localComfy?.error) el<HTMLElement>('local-comfy-progress').textContent = localComfy?.update_available ? '发现新版本，可以点击更新。' : '当前已是最新版本。'; }
  catch (error) { el<HTMLElement>('local-comfy-progress').textContent = `检查更新失败：${String(error)}`; }
  finally { localBusy = false; updateControls(); }
});

el<HTMLButtonElement>('update-comfy').addEventListener('click', async () => {
  const running = Boolean(latestStatus?.localReady);
  if (running && !(await confirmComfyStop())) return;
  localBusy = true; updateControls();
  try {
    if (running) {
      el<HTMLElement>('local-comfy-progress').textContent = '正在停止本地 ComfyUI…';
      await stopLocalComfyProcess();
      restartComfyAfterUpdate = true;
    }
    el<HTMLElement>('local-comfy-progress').textContent = '准备更新本地 ComfyUI…';
    await invoke('manage_local_comfy', { action: 'update' });
  } catch (error) {
    const stopped = restartComfyAfterUpdate;
    restartComfyAfterUpdate = false;
    localBusy = false;
    el<HTMLElement>('local-comfy-progress').textContent = stopped
      ? `无法开始更新：${String(error)}。本地 ComfyUI 已停止，可点击“打开 ComfyUI”重新启动。`
      : `无法开始更新：${String(error)}`;
    updateControls();
  }
});

providerSelect.addEventListener('change', markDirty);
imageSelect.addEventListener('change', markDirty);
videoSelect.addEventListener('change', markDirty);
document.querySelectorAll<HTMLInputElement>('[data-pack-kind]').forEach(input => input.addEventListener('input', () => {
  packDirty = true;
  el<HTMLElement>('pack-status').textContent = '组件链接已修改，请先检查并保存组件包。';
  markDirty();
}));
modelUrl.addEventListener('input', () => {
  inspectedModel = null;
  el<HTMLElement>('model-info').textContent = '请检查模型文件后再保存。';
  markDirty();
});

el<HTMLButtonElement>('inspect-model').addEventListener('click', async () => {
  const button = el<HTMLButtonElement>('inspect-model');
  button.disabled = true;
  el<HTMLElement>('model-info').textContent = '正在读取 Hugging Face 文件与校验信息…';
  try {
    inspectedModel = await invoke<ModelFile>('inspect_hf_model', { url: modelUrl.value.trim() });
    el<HTMLElement>('model-info').textContent = `${inspectedModel.filename} · ${(inspectedModel.size / 1e9).toFixed(1)} GB · 已锁定版本；需为 ComfyUI checkpoint。`;
  } catch (error) {
    inspectedModel = null;
    el<HTMLElement>('model-info').textContent = `检查失败：${String(error)}`;
  } finally { button.disabled = false; }
});

el<HTMLButtonElement>('save-config').addEventListener('click', async () => {
  const button = el<HTMLButtonElement>('save-config');
  button.disabled = true;
  try {
    if (packDirty) throw new Error('请先检查并保存已修改的组件包。');
    const image_model = imageSelect.value as ImageModel;
    const video_model = videoSelect.value as VideoModel;
    if (image_model === 'none' && video_model === 'none') throw new Error('至少选择一个模型。');
    if (image_model === 'checkpoint' && !inspectedModel) throw new Error('请先检查图片 checkpoint 文件。');
    const settings = await invoke<Settings>('save_settings', { settings: {
      provider: providerSelect.value, image_model, video_model,
      video_mode: savedSettings?.video_mode || 'ref2va',
      custom_model: image_model === 'checkpoint' ? inspectedModel : null,
    } });
    renderSettings(settings);
    el<HTMLElement>('config-message').textContent = '配置已保存；下一次新建机器将按此方案部署。';
    await refresh();
  } catch (error) { el<HTMLElement>('config-message').textContent = `保存失败：${String(error)}`; }
  finally { button.disabled = false; updateControls(); }
});

async function switchVideoMode(mode: 'fl2va' | 'ref2va') {
  if (!savedSettings) return;
  try {
    const settings = await invoke<Settings>('save_settings', { settings: {
      provider: savedSettings.provider, image_model: savedSettings.image_model,
      video_model: savedSettings.video_model, video_mode: mode,
      custom_model: savedSettings.custom_model,
    } });
    renderSettings(settings);
    el<HTMLElement>('mode-progress').textContent = mode === 'ref2va'
      ? '已切换。H3 节点的 first_frame 为参考图 1；reference_2 起为后续参考图。请将 LoRA 强度设为 0。'
      : '已切回首帧 / 尾帧模式。';
  } catch (error) { el<HTMLElement>('mode-progress').textContent = `切换失败：${String(error)}`; }
}

el<HTMLButtonElement>('switch-ref2va').addEventListener('click', () => { void switchVideoMode('ref2va'); });
el<HTMLButtonElement>('switch-fl2va').addEventListener('click', () => { void switchVideoMode('fl2va'); });
el<HTMLButtonElement>('download-ref2va').addEventListener('click', async () => {
  ref2vaBusy = true; updateControls();
  el<HTMLElement>('mode-progress').textContent = '正在启动云端多参考模型下载…';
  try { await invoke('prepare_ref2va'); }
  catch (error) { ref2vaBusy = false; el<HTMLElement>('mode-progress').textContent = `下载失败：${String(error)}`; updateControls(); }
});
el<HTMLButtonElement>('download-fl2va').addEventListener('click', async () => {
  ref2vaBusy = true; updateControls();
  el<HTMLElement>('mode-progress').textContent = '正在启动云端首帧模型下载…';
  try { await invoke('prepare_fl2va'); }
  catch (error) { ref2vaBusy = false; el<HTMLElement>('mode-progress').textContent = `下载失败：${String(error)}`; updateControls(); }
});

el<HTMLButtonElement>('save-pack').addEventListener('click', async () => {
  const button = el<HTMLButtonElement>('save-pack');
  button.disabled = true;
  el<HTMLElement>('pack-status').textContent = '正在核对 Hugging Face 文件信息，可能需要几十秒…';
  const pending = { provider: providerSelect.value, image: imageSelect.value, video: videoSelect.value };
  const urls: Record<'qwen' | 'h3', Record<string, string>> = { qwen: {}, h3: {} };
  document.querySelectorAll<HTMLInputElement>('[data-pack-kind]').forEach(input => {
    urls[input.dataset.packKind as 'qwen' | 'h3'][input.dataset.packRole || ''] = input.value.trim();
  });
  try {
    const settings = await invoke<Settings>('save_model_pack', { urls });
    renderSettings(settings);
    providerSelect.value = pending.provider;
    imageSelect.value = pending.image;
    videoSelect.value = pending.video;
    if (pending.provider !== settings.provider || pending.image !== settings.image_model || pending.video !== settings.video_model) markDirty();
    el<HTMLElement>('pack-status').textContent = '组件包已保存并锁定校验值。请确认上方模型选择并保存。';
  } catch (error) { el<HTMLElement>('pack-status').textContent = `组件包保存失败：${String(error)}`; }
  finally { button.disabled = false; updateControls(); }
});

for (const provider of ['runpod', 'vast'] as const) {
  el<HTMLButtonElement>(`save-key-${provider}`).addEventListener('click', async () => {
    const input = el<HTMLInputElement>(`api-key-${provider}`);
    const key = input.value.trim();
    if (!key) { el<HTMLElement>(`key-state-${provider}`).textContent = '请输入 API Key。'; return; }
    const button = el<HTMLButtonElement>(`save-key-${provider}`);
    button.disabled = true;
    try {
      const settings = await invoke<Settings>('save_api_key', { provider, key });
      input.value = '';
      savedSettings = settings;
      el<HTMLElement>(`key-badge-${provider}`).textContent = '已配置';
      el<HTMLElement>(`key-badge-${provider}`).classList.add('ready');
      el<HTMLElement>(`key-state-${provider}`).textContent = '密钥已保存在本机。';
      renderHome();
      updateControls();
    } catch (error) { el<HTMLElement>(`key-state-${provider}`).textContent = `保存失败：${String(error)}`; }
    finally { updateControls(); }
  });
}

await listen<Progress>('deployment-progress', event => {
  if (operating && progressMode !== 'start' &&
      ['creating', 'booting', 'installing', 'downloading', 'verifying', 'cloud-ready', 'tunnel', 'local', 'ready'].includes(event.payload.phase)) return;
  setProgress(event.payload);
});
await listen('gpu-ssh-ready', () => { void refresh().then(() => pollMetrics()); });
await listen<string>('comfy-progress', event => { el<HTMLElement>('local-comfy-progress').textContent = event.payload; });
await listen<{ok: boolean; message: string}>('comfy-finished', async event => {
  localBusy = false;
  const restart = restartComfyAfterUpdate;
  restartComfyAfterUpdate = false;
  el<HTMLElement>('local-comfy-progress').textContent = event.payload.ok ? event.payload.message : `操作失败：${event.payload.message}`;
  await refreshLocalComfy();
  if (!restart) return;
  if (!event.payload.ok) {
    nativeOpened = false;
    el<HTMLElement>('local-comfy-progress').textContent = '更新失败，本地 ComfyUI 已停止；处理问题后请点击“打开 ComfyUI”。';
    return;
  }
  el<HTMLElement>('local-comfy-progress').textContent = '更新完成，正在重新启动 ComfyUI…';
  nativeOpened = true;
  localOpening = true; updateControls();
  try {
    await invoke('open_comfy_window');
    el<HTMLElement>('local-comfy-progress').textContent = '更新完成，ComfyUI 已使用新版本重新打开。';
  } catch (error) {
    nativeOpened = false;
    el<HTMLElement>('local-comfy-progress').textContent = `更新完成，但重新启动 ComfyUI 失败：${String(error)}`;
  } finally {
    localOpening = false; updateControls();
  }
  await refresh();
});
await listen('deployment-finished', async () => {
  operating = false;
  await refresh();
  await loadSettings();
  if (!latestStatus?.podId && (lastError || progressMode === 'delete')) {
    clearOffers(lastError ? '启动未完成，请刷新报价后重新选择。' : '机器已删除，请查询新的实时报价。');
  }
  updateControls();
});
await listen<string>('video-mode-progress', event => { el<HTMLElement>('mode-progress').textContent = event.payload; });
await listen<{ok: boolean; message: string}>('video-mode-finished', async event => {
  ref2vaBusy = false;
  await loadSettings();
  el<HTMLElement>('mode-progress').textContent = event.payload.message;
  updateControls();
});
await Promise.all([refresh(), loadSettings(), refreshLocalComfy()]);
document.querySelector<HTMLElement>('.main')!.scrollTop = 0;
setInterval(() => { if (!operating) void refresh(); }, 15000);
setInterval(() => { void pollMetrics(); }, 1000);
