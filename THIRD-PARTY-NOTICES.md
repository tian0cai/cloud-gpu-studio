# Third-party notices / 第三方声明

Cloud GPU Studio's application license does **not** change the terms of third-party software or model files. Their copyright and trademark rights remain with their respective owners. Check the exact versions and their license texts before redistributing a binary or adding new dependencies.

本项目的应用许可**不改变**第三方软件或模型的独立授权。版权和商标仍归各自权利人所有。发布二进制包或增加依赖前，应核对所用版本及其完整许可文本。

| Component / 组件 | How used / 用法 | License / 许可 |
| --- | --- | --- |
| [Tauri](https://github.com/tauri-apps/tauri) and official updater/process plugins | Linked in the desktop app / 桌面应用依赖 | MIT or Apache-2.0; retain applicable notices / 保留相关版权声明 |
| [Vite](https://github.com/vitejs/vite) | Frontend build tool / 前端构建工具 | MIT |
| [TypeScript](https://github.com/microsoft/TypeScript) | Frontend compiler / 前端编译器 | Apache-2.0 |
| [ComfyUI](https://github.com/Comfy-Org/ComfyUI) | Installed separately from its official repository at user request / 用户操作时从官方仓库独立安装 | GPL-3.0; its source and notices are supplied by its own repository / 自身仓库提供源码与许可声明 |
| Hugging Face model files, including Qwen Image and MiniMax H3 | Downloaded on deployment; not included here / 部署时下载，本仓库不分发 | Per-model license and usage terms / 分别遵守各模型许可及使用条件 |
| RunPod and Vast.ai | User-selected hosted services / 用户自选云服务 | Service terms and pricing / 各平台服务条款与计费规则 |

The application bundle contains Cloud GPU Studio's GPL-licensed scripts and bridge node, public model manifests, and example workflows. It does not ship ComfyUI, Python packages, or model weights. During installation, the app can clone ComfyUI and link the bridge node into the installed ComfyUI. The project GPL does not change ComfyUI's own license or any model terms. A public binary release must include the corresponding source and applicable notices.

应用包包含本项目采用 GPL 授权的脚本和桥接节点、公开模型清单及示例工作流，不附带 ComfyUI、Python 依赖包或模型权重。安装时，应用可能克隆 ComfyUI 并把桥接节点链接到其中。本项目的 GPL 许可不改变 ComfyUI 自身或模型的许可。公开发布二进制包时，须提供对应源码及适用的许可声明。
