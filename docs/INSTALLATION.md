# 安装 Codex Lens / Install Codex Lens

本指南适用于 0.2.0 实验性桌面预览。下表是构建目标；公开状态与可用下载以 [GitHub Releases](https://github.com/liudabo-art/Codex-Lens/releases) 的 Assets 为准。[版本说明](RELEASE_NOTES.md)列出五个目标架构的完整文件名。若没有对应平台的资产，可从本仓库构建。运行前在同一 Release 下载 `SHA256SUMS.txt` 并核对所选包的 SHA-256。

This guide covers the experimental 0.2.0 desktop preview. The [release notes](RELEASE_NOTES.md) list the exact filenames for all five target architectures. Use the assets actually published on GitHub Releases and verify the selected package against `SHA256SUMS.txt` from the same Release. Build from source if your target package is unavailable.

| 系统 / System | 候选格式 / Package | 使用方式 / How to open |
| --- | --- | --- |
| Windows 10/11 x64 | Setup.exe 或 portable.zip | 每用户安装到开始菜单，或完整解压后运行 `Relay-Auditor.exe`。依赖系统已有 WebView2 Runtime。 |
| macOS Intel / Apple Silicon | x64 或 arm64 DMG | 打开磁盘镜像，把应用拖到 Applications，再从那里打开。构建目标为 macOS 13 或更新版本，实机兼容性待验证。当前候选未做 Apple 公证。 |
| Ubuntu 24.04 Linux x64 / arm64 | DEB 或 tar.gz | 用系统包管理器装 DEB，或解压后启动 `Relay-Auditor`。桌面需要 GTK 3 和 WebKitGTK 4.1。构建基线为 glibc 2.39。 |

可执行包包含 Python 与检测器。WebView2、WKWebView 或 WebKitGTK 由系统提供。所有平台都可从源码运行标准库 CLI。源码桌面端需先在隔离环境安装 [requirements-desktop.txt](../requirements-desktop.txt)。

Packages bundle Python and the engine. Native WebViews come from the operating system. The standard-library CLI can run from source on every supported platform; source desktop use first requires an isolated environment with [requirements-desktop.txt](../requirements-desktop.txt).

## 升级与首次打开 / Upgrade and first launch

升级前关闭旧版本。便携包整体解压到新目录，保留随包 `_internal`、worker 和资源，不把旧文件覆盖进去。Windows 未签名，macOS 仅临时签名且未公证，系统可能要求额外确认。当前没有完整原生 GUI 验收结论；包构建或冒烟通过不等于全部桌面功能实机通过。[验证状态](VERIFICATION.md)

Close the old version before upgrading. Extract portable packages into a new directory with all bundled files, including `_internal`, workers and resources. Windows packages are unsigned; macOS packages are ad hoc signed and not notarized. Your system may request additional confirmation. Full native GUI acceptance remains pending; package and smoke checks do not establish complete desktop acceptance.

同一桌面数据目录中的旧历史会补充稳定记录 ID，保留原题集版本和原分数。同一平台的源码桌面与打包桌面共用用户桌面数据目录；默认 CLI 使用仓库中的 `.relay-data/`，不会自动把该处历史迁移到桌面目录。Key 默认仅当前会话有效；Windows 可显式保存到目标专属凭据项。重启后未保存的 Key 需重新填写，周期检测与排队任务保持关闭。

Old history in the same desktop data directory receives stable record IDs and keeps its original suite version and marks. Source and packaged desktop apps on the same platform share the user's desktop data directory. The CLI defaults to the repository's `.relay-data/`, whose history is not automatically migrated into the desktop directory. Keys are session-only by default; Windows offers explicit target-owned vault storage. Re-enter unsaved keys after restarting. Periodic work and queues restart disabled.

首次打开后选择或导入目标，再按需添加官方同型号参考。120／180 题能力考试需要单独预览与确认预算；默认日预算不够整场考试。左侧「操作手册」提供随包离线教程与合成界面截图。所有模型结论仍待真实校准。

On first launch, add or import a target and optionally configure a matching official reference. A 120/180-question capability exam needs its own budget preview and confirmation; the default daily budget is insufficient for a full exam. Open **Operation Manual** in the sidebar for the packaged offline tutorial and synthetic interface screenshots. Model findings still await real calibration.

## 从源码启动 Windows 桌面端 / Windows source desktop

在仓库根目录运行以下命令，然后双击 `启动桌面端.cmd`。源码运行使用已准备的虚拟环境，构建成功后同一脚本可以启动本地候选。

From the repository root, prepare the isolated environment below. You can then use `启动桌面端.cmd`; it uses the prepared source environment or the local candidate after a successful build.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-desktop.txt
.\.venv\Scripts\python.exe -I -B desktop.py
```

Windows 提供目标专属的系统凭据保存。macOS 与 Linux 以当前会话保存 Key，重启后可在原目标贴入 Key 并点击开始。应用设置与匿名历史保存在各系统的用户数据目录。

The native build matrix covers Windows x64, Intel and Apple Silicon macOS, and x64 and ARM64 Ubuntu-family Linux. The [build process](RELEASING.md) separates package checks from native GUI acceptance. Windows setup and portable packages use the system WebView2 runtime. The macOS app uses WKWebView. Linux uses system GTK 3 and WebKitGTK 4.1. The Windows vault is opt-in. Other platforms keep keys for the current session.

更多 Windows 操作见 [Windows 桌面说明](../WINDOWS.md)。
