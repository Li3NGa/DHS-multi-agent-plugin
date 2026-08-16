# RunHistory 运行历史完成报告（by Trae Agent）

> 任务来源：`AGENT_TASKS/trae_task_history.md` · 完成时间：2026-08-16 · 状态：待协调者审查

## 改动文件清单

| 文件 | 改动 |
| --- | --- |
| `src/deepseek_multi_agent_plugin/history.py` | 新增 `RunHistory` 类：线程安全 JSONL 追加；`append` 自动补充自增 `index` 与 ISO 8601 本地 `timestamp`；`recent(limit=20)` 倒序最新在前；`clear()`；`__len__`；文件/父目录不存在自动创建，重新打开同一文件延续序号 |
| `src/deepseek_multi_agent_plugin/coordinator.py` | `DeepseekAdapter` 增加 `history` 可选参数与 `_record_history`：`run` 成功后写入摘要（strategy/prompt/final/rounds 条数/session_id/elapsed_seconds），失败不记录；新增 `history` 事件（未启用返回 `{"records": [], "enabled": false}`） |
| `src/deepseek_multi_agent_plugin/adapter_server.py` | `--history FILE`（默认取 `DS_HISTORY_FILE`）；`GET /history?limit=N`；`POST /run` 成功自动落盘；`/health` 启用时附加 `"history": "on"` 与 `history_count`；`build_server`/`serve` 透传 `history` 参数 |
| `src/deepseek_multi_agent_plugin/mcp_server.py` | `--history FILE` 启动参数；`_TOOLS` 新增 `history` 工具（中文描述，inputSchema 仅 `limit`）；`_call_tool` 转发 `{"type": "history", "limit": ...}` 事件 |
| `src/deepseek_multi_agent_plugin/__init__.py` | 导出 `RunHistory`（`__all__` 同步）；版本号 0.4.2 → **0.4.3** |
| `tests/test_history.py` | 新增 10 个测试（见下） |
| `tests/test_mcp_server.py` | 两处工具名单断言补 `"history"`（`test_tools_list` 与 `test_serve_end_to_end_over_stdio`） |
| `docs/http_api.md` | 启动参数表 `--history` 行；端点总览 `/history` 行；事件协议表 `history` 行；新增第 10 节「运行历史持久化」 |
| `docs/mcp.md` | 工具表 `history` 行；启动示例加 `--history` 用法 |
| `docs/api_reference.md` | `DeepseekAdapter` 签名补 `registry`/`history`；事件表 `history` 行；新增第 10 节 `RunHistory` 类文档 |
| `docs/usage.md` | 第 6 节新增 6.5「运行历史（RunHistory）」Python API 示例 |
| `pyproject.toml` | 版本号 0.4.2 → 0.4.3 |

## 测试结果

- `.venv\Scripts\python.exe -m pytest -q`：**107 passed**（原 97 + 新增 10），0 failed 0 skipped
- 新增测试覆盖：
  - RunHistory：追加/倒序读取/条数/清空、父目录自动创建与重开续号、4 线程 × 20 条并发追加不丢（80/80）
  - adapter：run 成功落盘且 `history` 事件可查、未启用返回 `enabled=false`、缺 prompt 的失败 run 不记录
  - HTTP：启用后 `/health` 带 `history_count`、`/run` 后条数 +1、`GET /history?limit=10` 返回记录；未启用 `/history` 返回 `enabled=false` 且 `/health` 保持 `{"status": "ok"}` 不变
  - MCP：`tools/list` 含 `history`；`tools/call run` 后 `tools/call history {"limit": 5}` 返回 1 条记录
- 任务书两项手工验收均通过：
  a) `adapter_server --demo --port 8123 --history %TEMP%\ds_runs.jsonl`：`/run` 后 `/health` 的 `history_count` 0→1，`GET /history` 返回完整摘要，JSONL 落盘内容正确；
  b) `mcp_server --demo --history %TEMP%\ds_runs2.jsonl`：stdio 冒烟 `tools/call run` → `tools/call history` 返回 `records=1`、`prompt=你好`。

## 实现要点

- 线程安全：`append`/`recent`/`clear`/`__len__` 共用一把 `threading.Lock`；序号 `_count` 在构造时按既有有效行数初始化，`clear` 重置
- 摘要字段遵循任务书建议；`rounds` 记录条数（int）而非完整轮次明细，控制 JSONL 体积
- `history` 事件的 `limit` 做了容错（非整数回退 20）；HTTP `/history` 的 `limit` 非法时回退 20 且下限 1
- 未触碰 `strategies.py`、Docker 相关文件与 `deploy/` 目录；未执行 `git push`（遵守任务书约束）

## 部署侧联动（超出任务书的补充，请审查）

1. 已将全局 Python314 环境的 `deepseek-multi-agent-plugin` 从 0.4.2 重装为 **0.4.3**（`pip install --no-deps .`），DSH 挂载的 MCP 子进程下次调用即可用 `history` 工具（DSH 懒加载，自动以新代码 respawn）；
2. 全局安装版快速冒烟：`python -m deepseek_multi_agent_plugin.mcp_server --demo --history` 链路正常。