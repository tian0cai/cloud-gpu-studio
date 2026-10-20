export type Language = 'zh-CN' | 'en-US';

const english: Record<string, string> = {
  'H3 注意力加速': 'H3 attention acceleration', '标准（画质优先）': 'Standard (quality first)', 'Sol-Attn（实验）': 'Sol-Attn (experimental)', '应用到下一次生成': 'Apply to next generation', '不会改变现有工作流；Sol-Attn 需要云端 CUDA 算子支持。': 'Keeps the current workflow; Sol-Attn needs a compatible cloud CUDA kernel.', 'Sol-Attn 已启用；下一次 H3 任务生效。请比较速度和参考图一致性。': 'Sol-Attn is on for the next H3 job. Compare speed and reference fidelity.', '标准注意力已启用；下一次 H3 任务生效。': 'Standard attention is on for the next H3 job.',
  '空闲自动删：关': 'Auto-delete: Off', '空闲自动删：开': 'Auto-delete: On', '应用运行期间，本地与云端队列空闲 5 分钟后弹出 15 秒倒计时；状态不明时不会自动删除。': 'While the app is running, 5 idle minutes across both queues trigger a 15-second countdown. Unknown status prevents deletion.', '取消部署会保留机器；开启自动删除后，双端队列空闲 5 分钟会弹出 15 秒倒计时。关闭应用不会自动删除。': 'Cancelling deployment keeps the machine. When enabled, auto-delete warns after both queues are idle for 5 minutes. Closing the app does not delete the machine.',
  '空闲自动删除': 'Automatic idle deletion', '已开启': 'On', '已关闭': 'Off', '本地与云端 ComfyUI 的执行中、等待中队列持续空闲 5 分钟后，弹出 15 秒倒计时窗口；没有选择“保留机器”就自动删除。GPU 使用率不参与判断。': 'After both local and cloud ComfyUI queues stay empty for 5 minutes, a 15-second countdown appears. The machine is deleted unless you choose Keep machine. GPU usage is not used.', '正在读取监控设置…': 'Loading idle monitor settings…', '应用需要保持运行；队列或连接状态无法确认时不会自动删除。': 'Keep the app running. Unknown queue or connection status prevents automatic deletion.', '已关闭；机器不会因空闲自动删除。': 'Off; the machine will not be deleted for idleness.', '监控已启用，等待机器连接及队列状态确认。': 'Monitoring is on; waiting for the machine and queue status.',
  '应用更新仅在桌面版中可用。': 'App updates are available in the desktop app.', '尚无已发布版本；发布首个 Release 后可检查更新。': 'No release is published yet. Update checks will work after the first release.',
  '查看部署详情 →': 'View deployment details →',
  '取消部署': 'Cancel deployment', '取消进度': 'Cancellation progress', '提交取消': 'Request cancellation', '停止部署': 'Stop deployment', '机器保留': 'Keep machine', '正在取消部署': 'Cancelling deployment', '正在停止部署；云端机器会保留并继续计费。': 'Stopping deployment; the cloud machine will remain and continue billing.', '正在等待机器创建请求结束，然后停止部署…': 'Waiting for the machine creation request to finish before stopping deployment…', '正在等待部署进程退出；机器状态不会因此改变。': 'Waiting for the deployment process to exit; the machine state will not change.', '正在停止安装、下载和连接；云端机器将保留。': 'Stopping installation, downloads, and connection; the cloud machine will remain.', '部署已取消，云端机器仍在计费。可继续部署或单独删除机器。': 'Deployment cancelled. The cloud machine is still billing; resume deployment or delete it separately.', '正在停止部署并删除机器…': 'Stopping deployment and deleting the machine…', '部署已取消，云端机器及临时磁盘已删除。': 'Deployment cancelled; the cloud machine and temporary disk were deleted.', '取消部署会保留仍在计费的机器；只有点击“删除云端机器”才会释放它。关闭应用也不会自动删除机器。': 'Cancelling deployment keeps the billable machine. Only Delete cloud machine releases it. Closing the app also keeps it running.',
  '应用更新': 'App updates', '正在检查应用版本…': 'Checking app version…', '检查应用更新': 'Check app updates', '下载并安装': 'Download and install', '发现新版本，可以点击更新。': 'A new version is available. Click Update.', '当前已是最新应用版本。': 'The app is up to date.', '正在下载应用更新…': 'Downloading app update…', '下载完成，正在安装…': 'Download finished. Installing…', '更新已安装，正在重启应用…': 'Update installed. Restarting app…', '请等待当前部署操作完成后再更新应用。': 'Wait for the current deployment to finish before updating.', '请先检查应用更新。': 'Check for app updates first.',
  '创建机器': 'Create machine', '启动 GPU': 'Start GPU', '安装与下载': 'Install and download', '校验与启动': 'Verify and start', '连接隧道': 'Connect tunnel', '本地界面': 'Local interface', '提交删除': 'Request deletion', '释放云端资源': 'Release cloud resources', '确认完成': 'Confirm completion', '正在准备启动…': 'Preparing launch…', '正在提交删除请求…': 'Submitting deletion request…',
  '已就绪': 'Ready', '已就绪 · 运行中': 'Ready · running', '准备安装本地 ComfyUI…': 'Preparing local ComfyUI installation…', '准备更新本地 ComfyUI…': 'Preparing local ComfyUI update…', '正在停止本地 ComfyUI…': 'Stopping local ComfyUI…', '正在检查官方仓库更新…': 'Checking the official repository for updates…', '当前已是最新版本。': 'Already up to date.', '价格上限已更改，请重新查询报价。': 'Price limit changed. Query offers again.', '多参考模式也已下载。': 'Multi-reference mode is also downloaded.', '多参考模式可按需下载。': 'Multi-reference mode can be downloaded on demand.', '首帧模式也已下载。': 'First-frame mode is also downloaded.', '首帧模式可按需下载。': 'First-frame mode can be downloaded on demand.', '首帧 / 尾帧 FL2VA 已启用': 'First/last-frame FL2VA enabled', '已切换。H3 节点的 first_frame 为参考图 1；reference_2 起为后续参考图。请将 LoRA 强度设为 0。': 'Switched. H3 first_frame is reference image 1; reference_2 onward are additional images. Set LoRA strength to 0.', '组件链接已修改，请先检查并保存组件包。': 'Component URLs changed. Inspect and save the pack first.', '正在读取 Hugging Face 文件与校验信息…': 'Reading Hugging Face file and checksum information…',
  '密钥已保存在本机；输入新密钥可替换。': 'Key stored on this computer. Enter a new key to replace it.', '尚未配置，请输入并保存。': 'Not configured. Enter and save a key.', '请先保存配置，再查询当前平台报价。': 'Save the configuration before querying offers.', '配置已加载，请查询当前平台报价。': 'Configuration loaded. Query live offers.', '检测到旧版网络存储仍在计费，请检查 RunPod 控制台。': 'An older network volume may still be billed. Check your RunPod dashboard.', '图片': 'Image', '视频': 'Video', '无图片模型': 'No image model', '无视频模型': 'No video model', '自选 H3': 'Custom H3', '自选 Qwen': 'Custom Qwen',
  '控制中心': 'Control center', '主导航': 'Main navigation', '总览': 'Overview', '模型方案': 'Model plan', '云端机器': 'Cloud machines', '账户设置': 'Accounts', '凭证仅保存在本机': 'Credentials stay on this computer',
  '创作工作台': 'Creative workspace', '模型、算力和本地 ComfyUI，一眼掌握。': 'Models, cloud GPUs and local ComfyUI in one place.', '正在检查状态': 'Checking status',
  '选择创作模型': 'Choose your models', '读取中': 'Loading', '图片模型': 'Image model', '视频模型': 'Video model', '官方 Qwen Image 2.1': 'Official Qwen Image 2.1', '自定义 Qwen 组件包': 'Custom Qwen component pack', '不部署图片模型': 'No image model', '官方 MiniMax H3 INT8': 'Official MiniMax H3 INT8', '自定义 H3 组件包': 'Custom H3 component pack', '不部署视频模型': 'No video model',
  '图片 checkpoint 文件链接': 'Image checkpoint file URL', '检查模型': 'Inspect model', '仅支持单文件 SD/SDXL checkpoint；视频模型请使用兼容的组件包。': 'Only single-file SD/SDXL checkpoints are supported; use a compatible component pack for video.',
  '自选组件包 · 编码器、VAE、LoRA': 'Custom components · encoder, VAE, LoRA', '图片 · Qwen 架构': 'Image · Qwen architecture', '视频 · H3 FL2VA 架构': 'Video · H3 FL2VA architecture', '主模型': 'Main model', '文本编码器': 'Text encoder', '视频 VAE': 'Video VAE', '音频 VAE': 'Audio VAE', 'LoRA（可选）': 'LoRA (optional)', 'Hugging Face 文件链接': 'Hugging Face file URL', '可留空': 'Optional',
  '检查并保存组件包': 'Inspect and save component pack', '每个链接会锁定版本、大小与 SHA-256；只支持上述两种节点架构。': 'Each URL is pinned to a revision, size and SHA-256; only the two node architectures above are supported.', '组件包保存在本机受限目录，不会写入公共仓库。多参考模式使用独立的 Ref2VA 主模型；现有 H3 文本编码器和 VAE 会复用，LoRA 需另行验证适配。': 'Component packs stay in a private local directory. Multi-reference mode uses a separate Ref2VA main model; the H3 encoder and VAEs are reused. Check LoRA compatibility separately.',
  '云平台': 'Cloud provider', '保存模型方案': 'Save model plan', '切换平台后自动保存，再查询该平台报价。': 'Changing provider saves it automatically; then query its offers.', '当前平台尚未配置 API Key，请到账户设置保存。': 'No API key for this provider. Save one in Accounts.', '已切换平台；请先到账户设置保存该平台 API Key。': 'Provider changed. Save its API key in Accounts first.', '正在保存云平台…': 'Saving cloud provider…', '正在切换平台，请稍候…': 'Changing provider…', '请先保存模型方案，再查询当前平台报价。': 'Save the model plan before querying offers.', '请选择价格条件并查询当前平台报价。': 'Set a price filter and query offers.', '平台未切换，请检查云端机器状态或账户设置。': 'Provider unchanged. Check cloud machine status or Accounts.', '选择平台并保存模型方案后查询报价，再选择一台机器；启动时会重新核对库存和价格。': 'Choose a provider and save the model plan, then query and select a machine. Stock and price are rechecked at launch.', '选择会在下一次新建机器时生效。': 'Changes apply to the next new machine.', 'H3 视频模式': 'H3 video mode', '多参考 Ref2VA 已启用': 'Multi-reference Ref2VA enabled', '下载多参考模型': 'Download multi-reference model', '切换到多参考': 'Switch to multi-reference', '下载首帧模型': 'Download first-frame model', '切回首帧模式': 'Switch to first-frame mode', '新机器优先下载 Ref2VA；首帧 FL2VA 可在机器启动后按需下载。': 'New machines download Ref2VA first; FL2VA can be downloaded later.',
  '新建机器预留双模式磁盘：RunPod 180 GB、Vast.ai 200 GB；磁盘费用由平台计入报价或另行计费。兼容的 80 GB 以上单卡，按需实例；Vast.ai 累计费用达到 $9 自动删除，RunPod 保留原 3 小时限制。报价筛选可留空。': 'New machines reserve 180 GB on RunPod or 200 GB on Vast.ai for both modes. Storage is billed by the provider. Requires a compatible on-demand GPU with at least 80 GB VRAM. Vast.ai auto-deletes at $9 accrued cost; RunPod retains a 3-hour limit. Price filtering is optional.',
  '选择显卡与价格': 'Choose GPU and price', '尚未查询': 'Not queried', '每小时价格筛选（美元，可留空）': 'Hourly price limit (USD, optional)', '不限': 'No limit', '显卡型号': 'GPU model', '全部兼容型号': 'All compatible models', '查询实时报价': 'Query live offers', '保存模型与平台后查询报价，再选择一台机器；启动时会重新核对库存和价格。': 'Save your models and provider, query offers, then choose a machine. Stock and price are checked again at launch.',
  '启动云端机器': 'Start cloud machine', '可先在 ComfyUI 页面编辑工作流，再按模型方案启动云端 GPU。': 'You can edit workflows in ComfyUI before starting the cloud GPU.', '启动并连接': 'Start and connect', '打开 ComfyUI': 'Open ComfyUI', '关闭 ComfyUI': 'Close ComfyUI', '删除云端机器': 'Delete cloud machine', '停止本地 ComfyUI 进程（127.0.0.1:8188）': 'Stop the local ComfyUI process (127.0.0.1:8188)', '关闭应用不会删除云端机器；本地 ComfyUI 会保持运行，可用“关闭 ComfyUI”随时停止。删除仅在点击按钮后执行。': 'Closing the app does not delete the cloud machine. Local ComfyUI stays running until you stop it. Deletion only happens when you click Delete.',
  '检查中': 'Checking', '云端实例': 'Cloud instance', '运行价格': 'Hourly price', '美元 / 小时': 'USD / hour', '账户余额': 'Account balance', '美元': 'USD', '连接状态': 'Connection', '本地端口 8188 / 8189': 'Local ports 8188 / 8189', '远程资源使用情况': 'Remote resource usage', '云端未启动': 'Cloud offline', 'CPU 使用率': 'CPU usage', 'GPU 使用率': 'GPU usage', '内存使用量': 'RAM usage', '显存使用量': 'VRAM usage', 'CPU 使用率曲线': 'CPU usage chart', 'GPU 使用率曲线': 'GPU usage chart', '内存使用率曲线': 'RAM usage chart', '显存使用率曲线': 'VRAM usage chart', '机器 SSH 就绪后约每秒采样一次；曲线保留最近 5 分钟。GPU 未就绪时暂不显示显存数据。': 'Samples are taken about once a second after SSH is ready. Charts show the last five minutes. VRAM is hidden until the GPU is ready.',
  '启动进度': 'Launch progress', '删除进度': 'Deletion progress', '等待操作。点击“启动并连接”开始。': 'Waiting. Click Start and connect to begin.', '查看运行日志': 'View activity log', '本地 ComfyUI': 'Local ComfyUI', '正在检查安装状态…': 'Checking installation…', '一键安装 / 修复': 'Install / repair', '检查更新': 'Check for updates', '更新 ComfyUI': 'Update ComfyUI', '安装在用户目录，工作流与输出文件不会随更新删除。': 'Installed in your home directory. Workflows and outputs are kept during updates.',
  '临时云端存储会随机器删除': 'Temporary cloud storage is deleted with the machine', '本地作品保留在 ComfyUI 输出目录': 'Local creations remain in the ComfyUI output directory', '停止本地 ComfyUI 并更新？': 'Stop local ComfyUI and update?', '本地 ComfyUI 正在运行（127.0.0.1:8188）。更新前会先停止它，正在生成的图片或视频会中断。更新成功后会自动重新启动。': 'Local ComfyUI is running (127.0.0.1:8188). Updating will stop it and interrupt active jobs. It will restart after a successful update.', '取消': 'Cancel', '停止并更新': 'Stop and update',
  '灵感在本地，': 'Ideas begin locally,', '算力在云端。': 'compute runs in the cloud.', '选好模型与显卡，再打开熟悉的 ComfyUI 工作流。每一步都在自己的位置，创作时只关注作品。': 'Choose models and a GPU, then open your familiar ComfyUI workflows. Everything is in its place so you can focus on creating.', '配置模型': 'Configure models', '查看云端机器': 'View cloud machines', '当前工作区': 'Current workspace', '正在读取配置': 'Loading configuration', '查看与调整': 'View and edit', '筛选显卡与报价': 'Filter GPUs and prices', '打开或管理': 'Open or manage', '运行概况': 'Activity', '查看部署详情': 'View deployment details', '等待操作': 'Waiting', '选择模型和显卡后即可启动云端机器。': 'Choose a model and GPU to start a cloud machine.',
  '平台 API Key': 'Provider API keys', 'RunPod 和 Vast.ai 的密钥可以分别配置。部署时使用“模型方案”中选定的平台；已保存的密钥不会显示在界面上。': 'Configure RunPod and Vast.ai keys separately. Deployment uses the provider selected in Model plan. Saved keys are never shown in the interface.', '输入新的 RunPod API Key': 'Enter a new RunPod API key', '输入新的 Vast.ai API Key': 'Enter a new Vast.ai API key', '保存': 'Save', '正在检查密钥状态…': 'Checking key status…',
  '先决定图片与视频模型，再保存部署方案。': 'Choose image and video models, then save the deployment plan.', '筛选显卡、启动实例，并查看部署进度与实时资源。': 'Filter GPUs, start an instance, and monitor deployment and live resources.', '编辑工作流、管理本地安装与更新。': 'Edit workflows and manage the local installation and updates.', '管理云平台凭证；密钥只保存在这台电脑上。': 'Manage provider credentials; keys stay on this computer.',
  '多参考模式': 'Multi-reference mode', '首帧模式': 'First-frame mode', '运行中': 'Running', '未启动': 'Stopped', '正在运行': 'Running', '已安装': 'Installed', '需要安装': 'Install needed', '操作遇到问题': 'Operation failed', '正在删除云端机器': 'Deleting cloud machine', '云端机器已就绪': 'Cloud machine ready', '正在准备云端机器': 'Preparing cloud machine', '连接已有机器': 'Connect to existing machine', '正在打开 ComfyUI…': 'Opening ComfyUI…', '打开 ComfyUI ↗': 'Open ComfyUI ↗', '需要修复': 'Repair needed', '未安装': 'Not installed', '有可用更新': 'Update available', '已是最新': 'Up to date', '未检测到版本': 'Version unavailable', '已配置': 'Configured', '未配置': 'Not configured', '已保存': 'Saved', '未保存': 'Unsaved', '模型方案有未保存更改': 'Model plan has unsaved changes', '查询中': 'Querying', '等待远程主机…': 'Waiting for remote host…', '等待远程指标…': 'Waiting for remote metrics…', '没有运行中的 Pod': 'No running Pod', '已连接': 'Connected', '待连接': 'Connecting', '离线': 'Offline', 'SSH 隧道与本地界面已就绪': 'SSH tunnel and local interface ready', '可以创作': 'Ready to create', '云端已启动': 'Cloud machine started', '云端离线': 'Cloud offline', '状态读取失败': 'Could not read status', '请选择筛选结果中的机器。': 'Select a machine from the offers.', '请选择一台机器。报价可能变化，启动前会重新核对。': 'Select a machine. The price may change and will be checked again at launch.', '当前没有符合部署要求的机器；可以稍后重试。': 'No machines meet the deployment requirements. Try again later.', '当前价格上限内没有符合部署要求的机器；可以提高上限或稍后重试。': 'No eligible machines under this price limit. Raise the limit or try later.',
  '正在启动本地 ComfyUI，无需等待云端 GPU…': 'Starting local ComfyUI; no need to wait for the cloud GPU…', '本地 ComfyUI 已打开；云端连接完成前可以编辑工作流。': 'Local ComfyUI is open. You can edit workflows while the cloud connects.', '正在关闭本地 ComfyUI…': 'Stopping local ComfyUI…', '本地 ComfyUI 已关闭，需要时可点击“打开 ComfyUI”重新启动。': 'Local ComfyUI stopped. Click Open ComfyUI to start it again.', '请先保存配置，再启动机器。': 'Save your configuration before starting a machine.', '价格筛选值必须是高于 $0 的有限数字；留空表示不限。': 'The price limit must be a finite number above $0; leave it blank for no limit.', '检查模型文件后再保存。': 'Inspect the model file before saving.', '请先检查并保存已修改的组件包。': 'Inspect and save the edited component pack first.', '至少选择一个模型。': 'Select at least one model.', '请先检查图片 checkpoint 文件。': 'Inspect the image checkpoint file first.', '配置已保存；下一次新建机器将按此方案部署。': 'Configuration saved. The next new machine will use this plan.', '已切回首帧 / 尾帧模式。': 'Switched to first/last-frame mode.', '正在启动云端多参考模型下载…': 'Starting cloud multi-reference model download…', '正在启动云端首帧模型下载…': 'Starting cloud first-frame model download…', '正在核对 Hugging Face 文件信息，可能需要几十秒…': 'Checking Hugging Face files; this may take tens of seconds…', '组件包已保存并锁定校验值。请确认上方模型选择并保存。': 'Component pack saved with pinned checksums. Confirm and save the model selection above.', '请输入 API Key。': 'Enter an API key.', '密钥已保存在本机。': 'Key saved on this computer.', '更新失败，本地 ComfyUI 已停止；处理问题后请点击“打开 ComfyUI”。': 'Update failed and local ComfyUI stopped. Resolve the issue, then click Open ComfyUI.', '更新完成，正在重新启动 ComfyUI…': 'Update complete. Restarting ComfyUI…', '更新完成，ComfyUI 已使用新版本重新打开。': 'Update complete. ComfyUI reopened with the new version.', '启动未完成，请刷新报价后重新选择。': 'Launch did not complete. Refresh offers and select again.', '机器已删除，请查询新的实时报价。': 'Machine deleted. Query live offers again.',
};

let language: Language = localStorage.getItem('cloud-gpu-studio-language') === 'en-US' ? 'en-US' : 'zh-CN';
const originals = new WeakMap<Text, string>();
const attributeOriginals = new WeakMap<Element, Map<string, string>>();
let observer: MutationObserver | undefined;

function translate(source: string): string {
  if (english[source]) return english[source];
  const patterns: Array<[RegExp, (...groups: string[]) => string]> = [
    [/^(\d+) 台可选$/, n => `${n} available`],
    [/^模型数据下载：(\d+)%$/, n => `Model download: ${n}%`],
    [/^正在查询 (.+) 的实时库存和价格…$/, provider => `Querying live ${provider} stock and prices…`],
    [/^当前平台：(.+)。切换后自动保存。$/, provider => `Current provider: ${provider}. Changes save automatically.`],
    [/^已切换至 (.+)，可以查询实时报价。$/, provider => `Switched to ${provider}. You can query live offers.`],
    [/^切换平台失败：(.+)$/, error => `Could not change provider: ${error}`],
    [/^已选择 (.+)，报价 \$(.+)\/小时。启动前会核对库存与价格上限。$/, (gpu, price) => `Selected ${gpu} at $${price}/hour. Stock and price will be checked at launch.`],
    [/^检查更新失败：(.+)$/, error => `Update check failed: ${error}`],
    [/^读取安装状态失败：(.+)$/, error => `Could not read installation status: ${error}`],
    [/^读取失败：(.+)$/, error => `Read failed: ${error}`],
    [/^配置读取失败：(.+)$/, error => `Could not load configuration: ${error}`],
    [/^保存失败：(.+)$/, error => `Save failed: ${error}`],
    [/^下载失败：(.+)$/, error => `Download failed: ${error}`],
    [/^应用更新检查失败：(.+)$/, error => `App update check failed: ${error}`],
    [/^应用更新失败：(.+)$/, error => `App update failed: ${error}`],
    [/^发现新版本 (.+)，可下载安装。$/, version => `Version ${version} is available to download and install.`],
    [/^切换失败：(.+)$/, error => `Switch failed: ${error}`],
    [/^检查失败：(.+)$/, error => `Inspection failed: ${error}`],
    [/^操作失败：(.+)$/, error => `Operation failed: ${error}`],
    [/^关闭本地 ComfyUI 失败：(.+)$/, error => `Could not stop local ComfyUI: ${error}`],
    [/^(.+)组件$/, name => `${translate(name)} components`],
    [/^完整组件包约 (.+) GB；实际下载量按所选图片和视频模型计算。$/, size => `Complete component pack: about ${size} GB; actual download depends on selected models.`],
    [/^最近采样 (.+)$/, time => `Last sample ${time}`],
    [/^队列已空闲，约 (\d+) 秒后弹出删除倒计时。$/, seconds => `Queues are idle. The deletion countdown appears in about ${seconds} seconds.`],
    [/^删除倒计时：(\d+) 秒。可在弹窗中保留机器。$/, seconds => `Deletion countdown: ${seconds} seconds. Use the pop-up to keep the machine.`],
    [/^(.+) · 版本 (.+)$/, (path, version) => `${path} · version ${version}`],
  ];
  for (const [pattern, render] of patterns) {
    const match = source.match(pattern);
    if (match) return render(...match.slice(1));
  }
  return source;
}

function visitText(node: Text) {
  const current = node.nodeValue || '';
  const known = originals.get(node);
  const original = known && (current === known || current === localize(known)) ? known : current;
  originals.set(node, original);
  const next = language === 'en-US' ? localize(original) : original;
  if (next !== current) node.nodeValue = next;
}

function localize(value: string): string {
  const trimmed = value.trim();
  return trimmed ? value.replace(trimmed, translate(trimmed)) : value;
}

function visitElement(element: Element) {
  if (element.matches('script, style')) return;
  for (const name of ['placeholder', 'title', 'aria-label']) {
    const current = element.getAttribute(name);
    if (current === null) continue;
    let map = attributeOriginals.get(element);
    if (!map) { map = new Map(); attributeOriginals.set(element, map); }
    const known = map.get(name);
    const original = known && (current === known || current === localize(known)) ? known : current;
    map.set(name, original);
    const next = language === 'en-US' ? localize(original) : original;
    if (next !== current) element.setAttribute(name, next);
  }
  for (const child of Array.from(element.childNodes)) {
    if (child.nodeType === Node.TEXT_NODE) visitText(child as Text);
    else if (child.nodeType === Node.ELEMENT_NODE) visitElement(child as Element);
  }
}

export function currentLanguage(): Language { return language; }

export function setLanguage(next: Language, root: Element) {
  language = next;
  localStorage.setItem('cloud-gpu-studio-language', next);
  document.documentElement.lang = next;
  observer?.disconnect();
  visitElement(root);
  observer?.observe(root, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['placeholder', 'title', 'aria-label'] });
}

export function startI18n(root: Element) {
  observer = new MutationObserver(records => {
    observer?.disconnect();
    for (const record of records) {
      if (record.type === 'characterData') visitText(record.target as Text);
      else if (record.type === 'attributes') visitElement(record.target as Element);
      else for (const node of Array.from(record.addedNodes)) {
        if (node.nodeType === Node.TEXT_NODE) visitText(node as Text);
        else if (node.nodeType === Node.ELEMENT_NODE) visitElement(node as Element);
      }
    }
    observer?.observe(root, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['placeholder', 'title', 'aria-label'] });
  });
  setLanguage(language, root);
}
