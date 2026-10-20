import { invoke } from '@tauri-apps/api/core';
import { getCurrentWindow } from '@tauri-apps/api/window';
import './idle-warning.css';

type Guard = { enabled: boolean; phase: string; secondsRemaining: number | null };
const english = localStorage.getItem('cloud-gpu-studio-language') === 'en-US';
document.querySelector<HTMLDivElement>('#app')!.innerHTML = `
  <div class="warning-icon">◷</div>
  <div class="warning-copy"><strong>${english ? 'Cloud GPU is idle' : '云端机器已空闲'}</strong>
    <p>${english ? 'Both ComfyUI queues have been empty for over 5 minutes. The machine will be deleted in' : '本地和云端 ComfyUI 队列已空闲超过 5 分钟。机器将在'}</p>
    <div class="countdown"><span id="seconds">15</span> ${english ? 'seconds' : '秒后自动删除'}</div>
    <small>${english ? 'Local images and videos will be kept.' : '本地图片和视频会保留。'}</small>
  </div>
  <div class="warning-actions"><button id="disable">${english ? 'Turn off auto-delete' : '关闭自动删除'}</button><button id="keep">${english ? 'Keep machine' : '保留机器'}</button><button id="delete">${english ? 'Delete now' : '立即删除'}</button></div>`;

let finished = false;
async function refresh() {
  if (finished) return;
  try {
    const guard = await invoke<Guard>('get_idle_guard');
    if (guard.phase !== 'warning') { finished = true; await getCurrentWindow().close(); return; }
    document.querySelector<HTMLElement>('#seconds')!.textContent = String(guard.secondsRemaining ?? 0);
  } catch { /* Keep the window visible if the state query fails. */ }
}
document.querySelector<HTMLButtonElement>('#keep')!.onclick = async () => {
  if (finished) return;
  finished = true;
  try { await invoke('keep_idle_machine'); } catch { finished = false; }
};
document.querySelector<HTMLButtonElement>('#disable')!.onclick = async () => {
  if (finished) return;
  finished = true;
  try { await invoke('set_idle_guard', { enabled: false }); } catch { finished = false; }
};
document.querySelector<HTMLButtonElement>('#delete')!.onclick = async () => {
  if (finished) return;
  finished = true;
  try { await invoke('delete_idle_machine'); } catch { finished = false; }
};
void refresh();
setInterval(() => { void refresh(); }, 250);
