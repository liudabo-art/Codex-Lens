# 发布候选 / Release candidates

本项目的 `VERSION` 是安装包版本来源。0.1.0 是当前候选版本。本仓库独立管理源码和候选构建。正式安装包、Git 标签和 GitHub Releases 由维护者单独审阅。普通推送运行合成检查，原生包由手动工作流构建。

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
2. 确认 GitHub 身份与目标 `owner/repository` 后，在批准的仓库运行 [原生构建流程](../.github/workflows/build-native.yml)。流程为手动触发，产物用于验证。
3. 检查各系统和架构的安装、启动、卸载及包哈希。记录实测平台、签名和公证状态。只有经确认的产物进入 Release。

The build workflow is manual and uses synthetic tests. It produces build artifacts. Publishing a GitHub Release is a separate maintainer action. PyInstaller requires a builder on each target operating system. [PyInstaller manual](https://pyinstaller.org/en/stable/index.html)
