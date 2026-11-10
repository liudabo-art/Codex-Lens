# 验证记录 / Verification

## 0.1.0 桌面发布准备

- 本机 Windows 标准库环境运行 185 项 Python 测试，184 项通过，1 项按桌面依赖条件跳过。Node 14 项通过。
- 在 Git Bash 上用合成文件验证了发布清单。五组文件完整时生成总 SHA-256，缺少架构文件或文件被改动时拒绝发布。Windows 清单的 CRLF 输入包含在验证中。
- 原生构建和安装冒烟结果以该版本对应的 [Native desktop packages](https://github.com/liudabo-art/Codex-Lens/actions/workflows/build-native.yml) 运行为准。

## 0.1.0 独立源码基线

- Windows／Python 3.13 标准库环境运行 185 项测试，184 项通过，1 项需要桌面依赖的测试按条件跳过。Node 14 项通过。
- 从独立仓库根目录运行离线 demo 和校准模拟。模拟返回 128 个合成结果组合，真实模型请求为 0。
- 同一版检测器在本地完成 Windows x64 便携包和冻结离线 worker 验证。通过合成回环界面验证断流后继续、三次失败后中止和保存前面的成绩。
- Windows Setup、macOS、Linux 实机验收与真实模型校准分别跟踪。仓库的手动原生工作流生成候选构建。
