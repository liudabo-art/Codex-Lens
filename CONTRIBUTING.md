# 贡献指南 / Contributing

Codex Lens 在此独立开发。修改检测、界面、协议或报告时，可在个人开发分支提交 PR。请说明改动覆盖的模型家族、协议和证据范围，并附可复现的合成用例。

## 本地验证

在仓库根目录执行以下命令。核心只需 Python 3.11+ 标准库。前端检查需 Node.js。桌面与原生打包依赖见[构建说明](docs/RELEASING.md)。

```text
python -B -m unittest discover -s tests -v
node tests/test_dashboard.cjs
python -I -S -B run.py demo
python -I -S -B run.py calibration-simulate --trials 100 --seed 42
```

普通 GitHub Actions 使用合成数据。真实 Key、配置、原始响应、业务正文、真实日志和报告留在本机。反馈请用合成夹具、匿名计数和稳定错误码。 [安全与隐私](SECURITY.md)

## 改动时同步

- 改题面、评分、任务配比时更新题集版本，保留旧报告原有证据边界。
- 修改接口或输出时检查匿名字段过滤，并同步双语 README、方法说明和接入契约。
- 修改桌面交互时验证实际控件、进度与中止提示，再更新本机启动脚本所指的候选。
- 将用户可见改动记录在 [CHANGELOG.md](CHANGELOG.md)。支持平台、实验结论及发布状态以实际验证为准。

See [architecture and extension points](docs/EXTENDING.md) and the [file guide](FILE_GUIDE.md) for adding a task or protocol. Future integration with the upstream Token Usage Monitor is reviewed separately. [Development roadmap](docs/DEVELOPMENT_PLAN.md)
