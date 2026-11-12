# 发布候选 / Release candidates

本项目的 `VERSION` 是安装包版本来源，当前为 0.2.0。本仓库独立管理源码和候选构建。提交、推送、Git 标签和 GitHub Release 需要明确的用户发布任务；文档或版本更新本身不构成授权。普通推送运行合成检查。原生工作流支持手动候选构建与专用发布分支。发布状态与日期以实际 GitHub Release 为准。

`VERSION` is the authoritative package version, currently 0.2.0. Commits, pushes, tags and publication require an explicit user task. Manual workflow runs build candidates; release-branch pushes can publish a prerelease after the configured gates. A version or documentation update alone does not authorize publication.

## 本机构建

在目标操作系统上使用隔离环境。

```text
python -m venv .venv
python -m pip install -r requirements-build.txt
python -B -m unittest discover -s tests -v
node tests/test_dashboard.cjs
python -B build_tools/build.py
```

创建虚拟环境后，先激活它或使用其中的 Python。Windows 安装器需要 Inno Setup 6。只验证 Windows 便携版可传入 `--portable-only`。macOS 用系统磁盘镜像工具，Linux 用发行版的包工具。PyInstaller 在产物的目标系统上运行。

## 本机预览交付

每次交付影响桌面预览的改动时，用对应候选通过本机验证。Windows 构建成功后会写入 `dist/latest-desktop.cmd`。如果候选在独立目录构建，先校验归档和界面资源，再将整套候选放到 `dist` 的独立子目录并更新该指针。确认从子项目的 `启动桌面端.cmd` 可定位到新版 EXE。旧候选可保留供复查。

完成后，在支持本机页面的 Codex 侧边栏打开合成预览。预览使用合成数据并绑定回环地址。真实配置与检测操作通过本机桌面入口使用。

## 审阅和发布

源码开源与原生安装包发布分别验收。可查看 [已完成的验证](VERIFICATION.md) 和 [当前变更](../CHANGELOG.md)。

1. 用 `python -B build_tools/stage_source.py` 导出明确允许的源码、合成测试、文档和静态资源。审阅源码包和文件清单，确保只有公开内容。
2. 确认 GitHub 身份与目标 `owner/repository` 后，在批准的仓库运行 [原生构建流程](../.github/workflows/build-native.yml)。手动触发只生成候选产物。
3. 五个原生任务分别构建 Windows x64、macOS x64/arm64 与 Linux x64/arm64，并做固定 worker、资源与包冒烟；工作流另做 Windows 安装/卸载、macOS 挂载和 Linux 解包检查。逐项核对结果、文件清单及包哈希，记录实际签名、公证和实机验证状态。完整原生 GUI 验收另行记录，不能由这些检查替代。

4. 发布时更新 `VERSION`、变更记录和 [发布说明](RELEASE_NOTES.md)。审阅后的提交应同时位于 `main` 和 `codex/release-v<版本>`。五个原生任务均通过、文件清单及 SHA-256 完整后，工作流才创建并公开该版本的预发布。已有标签和 Release 由维护者审阅处理。

0.2.0 使用 `codex/release-v0.2.0` 与 `v0.2.0`；八个安装包的准确名称见[发布说明](RELEASE_NOTES.md)。完整 Release 另含合并后的 `SHA256SUMS.txt`。版本分支必须与 `VERSION` 一致，发布时 `main` 必须指向同一提交，且同名标签与 Release 不得已存在。

准备 0.2.0 文档时已有本地 Windows 便携候选及合成测试记录；其他平台是否成功以本轮 CI 为准。完整原生 GUI 验收与真实模型校准仍开放。Windows 产物未签名，macOS 使用临时签名且未做 Apple 公证；不要将打包成功写成签名、完整桌面验收或真实校准通过。

A manual workflow run produces candidate artifacts. In the standalone repository, the version-specific release branch builds and verifies all eight packages across five targets before publishing a prerelease with `SHA256SUMS.txt`. The release branch must match `VERSION`, `main` must point to the same commit, and the tag and Release must be new. These package, worker and installation checks do not replace native GUI acceptance or real model calibration. Windows packages remain unsigned; macOS packages use ad hoc signing without notarization. PyInstaller requires a builder on each target operating system. [PyInstaller manual](https://pyinstaller.org/en/stable/index.html)
