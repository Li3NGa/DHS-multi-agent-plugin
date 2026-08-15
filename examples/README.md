# 示例代码（Examples）

以下脚本克隆仓库后即可直接运行（脚本内部会自动把 `../src` 加入 `sys.path`，无需先安装包）：

| 脚本 | 说明 | 是否需要 API Key |
| --- | --- | --- |
| [demo_strategies.py](demo_strategies.py) | 用 mock Agent 依次演示全部 5 种协作策略 | 否 |
| [demo_deepseek_team.py](demo_deepseek_team.py) | 用真实 DeepSeek API 跑一场三人辩论 | 是（`DEEPSEEK_API_KEY`） |
| [run_http_server.py](run_http_server.py) | 启动 HTTP 适配服务（端口 8000） | 否 |

## 快速试跑

```bash
python examples/demo_strategies.py

# 或安装包之后用命令行体验同样的功能：
deepseek-multi-agent run --demo --strategy debate --rounds 2 --prompt "你好"
```

## 自定义实验

- 把 `demo_strategies.py` 里的 `build_team()` 换成你自己的团队（如 DeepSeek Agent），
  即可观察同一任务在 5 种策略下的不同过程与结论；
- 修改 `coord.run(...)` 的 `prompt`、`rounds`、`judge`、`order` 等参数，理解各策略的行为差异；
- 更多参数说明见 [docs/usage.md](../docs/usage.md)。
