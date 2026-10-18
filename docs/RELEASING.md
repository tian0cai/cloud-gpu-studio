# Releasing Cloud GPU Studio / 发布指南

1. Create the GitHub repository `tian0cai/cloud-gpu-studio`. Install the official [GitHub CLI](https://cli.github.com/) and run `gh auth login` on this computer, choosing **GitHub.com → HTTPS → Login with a web browser**. The author completes the browser authentication. Do not send a GitHub session token, personal access token, SSH private key, or updater signing key in chat. SSH credentials alone do not grant access to repository creation or Actions secret management.
2. Add the Git remote with `git remote add origin https://github.com/tian0cai/cloud-gpu-studio.git`. Review all staged and untracked files, then make the initial commit and push `main`. Keep the repository private while reviewing legal terms and release assets; make it public only when ready.
3. Keep the updater signing private key at `work/keys/updater.key` backed up securely. Its matching **public** key is in `src-tauri/tauri.conf.json`. Add the private key to the repository's GitHub Actions secret without printing it: `gh secret set TAURI_SIGNING_PRIVATE_KEY --repo tian0cai/cloud-gpu-studio < work/keys/updater.key`. This key was generated without a password for the initial local build; do not create the optional password secret unless rotating to a password-protected key. Never commit or publish the private key. If it is lost, already installed apps will reject future updates signed with another key.
4. Set a version: `npm run version:set -- 0.2.0`. Run `npm run release:check`, `npm run build`, tests, and `npm run release:build`. Inspect the `.app`, `.app.tar.gz`, `.sig`, bundle resources, and GPL notices. Ensure the public tag includes the complete corresponding source and build scripts for the binary. Commit and push the version change.
5. Run `npm run release:publish`. This creates/pushes `v0.2.0` and triggers `.github/workflows/release.yml`. GitHub Actions builds a **draft** Release and `latest.json`. Verify assets and notes in the draft, then publish it in GitHub. Installed apps will then detect the new signed version.

The first pipeline targets macOS Apple Silicon only. Before broad public distribution, configure Apple Developer ID signing and notarization, validate installation on a clean Mac, and review GPL source-distribution compliance, model terms, and third-party notices. The updater cannot be tested end-to-end until at least one release is published and a later version exists.

---

1. 创建 `tian0cai/cloud-gpu-studio` 仓库。在本机安装官方 [GitHub CLI](https://cli.github.com/)，运行 `gh auth login`，选择 **GitHub.com → HTTPS → 在浏览器中登录**，由仓库所有者自己完成网页登录。不要在聊天中发送 GitHub Session、访问令牌、SSH 私钥或更新签名私钥。SSH Key 只负责 Git 连接，不够用于创建仓库和配置 Actions 密钥。
2. 运行 `git remote add origin https://github.com/tian0cai/cloud-gpu-studio.git`。检查暂存及未跟踪文件，完成首次提交并推送 `main`。许可、二进制包及法律问题审核完毕前，可先保持私有仓库。
3. 将 `work/keys/updater.key` 在安全位置备份。对应的**公钥**已经写入 `src-tauri/tauri.conf.json`。通过 `gh secret set TAURI_SIGNING_PRIVATE_KEY --repo tian0cai/cloud-gpu-studio < work/keys/updater.key` 保存到 Actions Secret，命令不会把私钥正文打印到终端。初次本地构建使用的是无密码私钥；除非今后更换为加密私钥，否则不需要密码 Secret。私钥一旦遗失，已经安装的应用将无法接受用其他密钥签名的新版本。
4. 运行 `npm run version:set -- 0.2.0`，再运行 `npm run release:check`、`npm run build`、测试和 `npm run release:build`。检查 `.app`、更新归档、签名、包内资源及 GPL 声明；确认公开版本标签包含该二进制包的完整对应源码和构建脚本，再提交并推送版本变更。
5. 运行 `npm run release:publish`，推送版本标签并触发 GitHub Actions。工作流会生成**草稿 Release** 和 `latest.json`。核对文件与说明后在 GitHub 公开草稿，安装版才会收到升级提示。

首次流程仅覆盖 macOS Apple Silicon。大范围公开发布前，应补齐 Apple Developer ID 签名及公证，并在干净的 Mac 上验证安装；同时核对 GPL 对应源码分发义务、模型条款及第三方声明。自动升级的端到端验证必须等首次发布和第二个版本存在后才能完成。
