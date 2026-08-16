# MCP 服务器（Model Context Protocol）

插件内置了一个 **MCP stdio 服务器**，把多智能体协作引擎暴露给任何支持 MCP 的
Agent 宿主（DSH Harness 的 dsh-mcp-client、Codex、Claude Code/Desktop、Trae 等）。
通过 MCP，其他 agent 可以把本插件当作"工具"直接调用：让一支 DeepSeek 团队跑
辩论/接力/主管等协作策略，并拿回最终结论。

> 实现文件：`src/deepseek_multi_agent_plugin/mcp_server.py`（纯标准库，
> newline-delimited JSON-RPC over stdin/stdout，协议版本 2025-03-26；
> initialize 时支持版本协商：客户端请求受支持版本则回该版本，否则回默认 2025-03-26）。

## 1. 启动

```bash
# 演示模式（两个 mock agent）
python -m deepseek_multi_agent_plugin.mcp_server --demo

# 加载配置文件团队
python -m deepseek_multi_agent_plugin.mcp_server --config example_config.yaml

# 启用运行历史持久化（新增 history 工具）
python -m deepseek_multi_agent_plugin.mcp_server --demo --history runs.jsonl
```

服务从 stdin 读取 JSON-RPC 请求、向 stdout 写响应（一行一个 JSON），
日志走 stderr（可用 `MCP_LOG_LEVEL=DEBUG` 调级别）。

## 2. 暴露的工具

| 工具 | 说明 | 关键参数 |
| --- | --- | --- |
| `run` | 运行一次多智能体协作任务，返回 final + 每轮明细 | `prompt`（必填）、`strategy`、`rounds`、`session_id`、`judge`、`order`、`workers`、`timeout` |
| `agents` | 列出已注册 agent（name/role/provider/model） | `session_id`（可选） |
| `register` | 动态注册 agent（与 HTTP register 事件同构） | `agents`（必填）、`session_id`（可选） |
| `status` | 状态摘要（agent 列表、auto 策略、会话数） | — |
| `history` | 查询最近的协作运行历史（需 `--history` 启动） | `limit`（可选，默认 20） |

`strategy` 枚举：`auto` / `broadcast` / `sequential` / `debate` / `supervisor` /
`consensus` / `relay`。

`session_id` 用于会话隔离：带同一 session_id 的调用共享独立的 agent 注册表与
对话记忆（`SessionRegistry`），不同会话互不可见。

## 3. 对接示例

### 3.1 Codex（config.toml）

```toml
[mcp_servers.multiagent]
command = "python"
args = ["-m", "deepseek_multi_agent_plugin.mcp_server", "--config", "C:/path/to/deepseek-multi-agent-plugin/example_config.yaml"]
```

之后 Codex 会话中可直接调用 `mcp__multiagent__run` 等工具。

### 3.2 DSH Harness

DSH 通过 cordis.patch.yml 热加载 MCP 服务器（工具名形如 `mcp__multiagent__run`），
懒加载，首次调用自动拉起子进程。

### 3.3 手工冒烟（stdio 协议）

```bash
printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26"}}\n' \
  | python -m deepseek_multi_agent_plugin.mcp_server --demo
```

`tools/list` 与 `tools/call` 均为标准 JSON-RPC 2.0，详见测试
`tests/test_mcp_server.py`（含端到端 stdio 用例）。

## 4. 与 HTTP 适配服务的关系

MCP 服务器与 HTTP 适配服务共用同一套 `DeepseekAdapter` 事件协议，
工具调用被翻译成对应事件：`tools/call run` → `{"type":"run",...}`。
因此两者能力完全一致，区别仅在传输层（stdio JSON-RPC vs HTTP JSON）。

## 5. 限制

- stdio 模式下不建议直接并发会话写入 stdout；多会话并发请用 HTTP 服务；
- `custom` 类型 agent 无法经配置注册（需要 Python 对象），LLM/mock/http 均可；
- MCP 协议目前不支持流式输出，`run` 一次性返回完整结果。
