# Codex 代码质量与优化审查完成报告

> 任务来源：`AGENT_TASKS/codex_task_quality.md` · 完成时间：2026-08-16 · 状态：待协调者审查

## 改动文件清单

| 文件 | 改动 |
| --- | --- |
| `src/deepseek_multi_agent_plugin/strategies.py` | 新增 `STRATEGY_NAMES = ("auto", *STRATEGIES)`，作为 CLI / MCP 策略名单一来源 |
| `src/deepseek_multi_agent_plugin/cli.py` | `run --strategy` 改用 `STRATEGY_NAMES`；`serve` 子命令新增 `--history`、`--history-prompt-limit`、`--history-final-limit` |
| `src/deepseek_multi_agent_plugin/adapter_server.py` | 请求体上限 `MAX_REQUEST_BYTES`（超限返回 413）；token 改用 `hmac.compare_digest` 常量时间比较；`/history` 的 limit 上限 500；`build_server`/`serve`/`main` 透传 history 截断参数 |
| `src/deepseek_multi_agent_plugin/mcp_server.py` | `_STRATEGIES` 改为从 `STRATEGY_NAMES` 派生；`main` 新增 history 截断参数 |
| `src/deepseek_multi_agent_plugin/coordinator.py` | `DeepseekAdapter` 新增 `history_prompt_limit` / `history_final_limit`，落盘前可选截断 prompt / final（默认不截断，保持兼容） |
| `src/deepseek_multi_agent_plugin/agents.py` | `chat_completion` 重试尊重 `Retry-After`、退避上限 8 秒、JSON 解析失败也重试 |
| `tests/test_agents.py` | 新增 Retry-After 生效、坏 JSON 重试两个测试 |
| `tests/test_server.py` | 新增请求体超限 413、token 鉴权（无/错/正确）测试 |
| `tests/test_history.py` | 新增 history prompt/final 截断测试 |

## 测试结果

`.venv\Scripts\python.exe -m pytest -q` → **115 passed**（原 110 + 新增 5），0 failed，0 skipped。

## 参考的 GitHub 社区实践

- 请求体大小上限：参考 Codex→DeepSeek 本地代理项目 `MAX_BODY_BYTES` 防护模式，防止异常请求拖垮内存。
- LLM 重试：参考 `llmwire` / `retry-client` 等社区客户端，指数退避 + 尊重 `Retry-After` + 上限保护，并对瞬时 JSON 解析失败重试。
- 策略名单一来源：CLI/MCP 的 choices 不再硬编码，而是从 `STRATEGIES` 注册表派生，避免新增策略时漏改两处。
- 常量时间 token 比较：使用 `hmac.compare_digest`，避免 Authorization 头时序侧信道。

## 兼容性与约束

- 未改动 `dsh/`、`deploy/`、Docker 相关文件、`.github/workflows/*`；
- 未执行 `git push`；未引入 `conftest.py` / `_probe*.py` 等调试产物；
- 保持纯标准库实现与 Python >= 3.10；
- `run()` 结果结构、HTTP 端点路径与字段、MCP 工具名与 inputSchema、既有 CLI 参数均未破坏。

## 后续可持续优化项（供协调者排期）

1. `RunHistory.recent` 目前全文件读取，可改为倒序读尾部 N 行，避免历史文件变大后每次查询 O(n)；
2. `chat_completion` 可加入带抖动的退避（full jitter），并支持从环境变量覆盖 `MAX_BACKOFF_SECONDS`；
3. HTTP 服务器可增加请求日志脱敏（不打印 Authorization 与 prompt 原文）；
4. MCP `PROTOCOL_VERSION` 可评估升级到更新的协议版本；
5. CLI `serve` 与 `adapter_server` 参数已对齐，后续可补充 CLI 层自动化测试。
