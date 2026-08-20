# HTTP 服务接口（HTTP Adapter API）

适配服务把插件的全部能力暴露为 HTTP JSON 接口，方便 DeepSeek Harness、脚本、其他服务调用。
服务仅用 Python 标准库实现（`http.server`），无额外依赖。

> 上一级：[详细使用说明](usage.md)

---

## 1. 启动

```bash
# 方式一：模块启动（推荐）
python -m deepseek_multi_agent_plugin.adapters.http --port 8000 --demo
# 旧路径 python -m deepseek_multi_agent_plugin.adapter_server 仍然可用

# 方式二：安装后的命令行入口
deepseek-plugin-runner --port 8000 --demo
deepseek-multi-agent serve --port 8000 --demo

# 用配置文件加载团队（推荐用于生产）
deepseek-multi-agent serve --config example_config.yaml --port 8000
```

| 启动参数 | 说明 |
| --- | --- |
| `--host` | 监听地址，默认 `127.0.0.1` |
| `--port` | 端口，默认 `8000` |
| `--config` | YAML/JSON 配置文件（指定后忽略 `--demo`） |
| `--demo` | 注册 `alpha`、`beta` 两个 mock Agent |
| `--history` | 运行历史 JSONL 文件路径（默认取环境变量 `DS_HISTORY_FILE`；未设置则不启用持久化） |
| `--history-prompt-limit` / `--history-final-limit` | 历史记录中 prompt / final 字段的截断长度 |
| `--token` | Bearer 令牌（默认取 `DS_AGENT_TOKEN`）；单令牌等于 admin |
| `--role ROLE:TOKEN` | 分角色令牌，可重复；或环境变量 `DS_AGENT_ROLES` 传 JSON 对象 `{role: token}` |
| `--session-ttl` | 会话存活秒数，过期自动清理 |
| `--max-sessions` | 会话数量上限，满时按 LRU 淘汰 |

---

## 2. 鉴权（RBAC）

不配置任何令牌时服务为本地开放模式（适合本机调试）。配置令牌后，所有请求需带
`Authorization: Bearer <token>`，端点按最低角色鉴权：

```bash
# 单令牌 = admin（与旧版 --token 行为一致）
python -m deepseek_multi_agent_plugin.adapters.http --port 8000 --demo --token s3cret

# 分角色令牌
python -m deepseek_multi_agent_plugin.adapters.http --port 8000 --demo \
  --role readonly:ro-token --role user:u-token \
  --role operator:op-token --role admin:ad-token
```

| 角色 | 权限 |
| --- | --- |
| `readonly` | 健康检查、列出 agent、状态 |
| `user` | readonly + 执行协作任务（`/run`） |
| `operator` | user + 运行 Trace、历史、会话管理 |
| `admin` | 全部权限，含动态注册 agent |

未带令牌返回 401；权限不足返回 403 并指明所需角色。服务端日志与异常栈在落盘前
对令牌与 API Key 做脱敏。

---

## 3. 端点总览

| 端点 | 方法 | 最低角色 | 说明 |
| --- | --- | --- | --- |
| `/health` | GET | readonly | 健康检查 |
| `/agents` | GET | readonly | 列出已注册 Agent |
| `/status` | GET | readonly | 版本 + agent 健康计数 + 运行数 |
| `/run` | POST | user | 执行一次协作任务 |
| `/runs` | GET | operator | 最近运行 Trace 摘要 |
| `/runs/{id}` | GET | operator | 单次运行完整 Trace |
| `/history` | GET | operator | 查询最近运行历史（需 `--history` 启动） |
| `/sessions` | GET | operator | 会话统计（顺带清理过期会话） |
| `/sessions/cleanup` | POST | operator | 强制清理过期会话，返回被清退的 id |
| `/sessions/{id}` | DELETE | operator | 删除指定会话 |
| `/register` | POST | admin | 动态注册 Agent（运行中扩员） |

所有响应均为 JSON（`application/json; charset=utf-8`）。

---

## 4. GET /health

```bash
curl -s localhost:8000/health
```

```json
{ "status": "ok" }
```

---

## 5. GET /agents

```bash
curl -s localhost:8000/agents
```

```json
{
  "agents": [
    { "name": "alpha", "role": null, "provider": null, "model": null, "has_handler": true },
    { "name": "beta", "role": null, "provider": null, "model": null, "has_handler": true }
  ]
}
```

---

## 6. POST /run

执行一次协作任务。请求体是一个事件对象：

```json
{
  "type": "run",
  "prompt": "AI 安全最重要的问题是什么？",
  "strategy": "debate",
  "rounds": 3,
  "judge": "judge",
  "order": ["critic", "researcher"],
  "workers": ["w1", "w2"],
  "timeout": 30,
  "session_id": "task-42",
  "budget": { "max_calls": 20, "max_seconds": 120 }
}
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `type` | 是 | 固定为 `"run"` |
| `prompt` | 是 | 任务提示词；缺失返回 400 `{"error": "missing prompt"}` |
| `strategy` | 否 | `auto`（默认）/ `broadcast` / `sequential` / `debate` / `supervisor` / `consensus` / `relay` |
| `rounds` | 否 | 轮数（broadcast/debate/relay） |
| `judge` | 否 | 裁判 Agent 名（debate/consensus） |
| `order` | 否 | 顺序列表（sequential/relay） |
| `workers` | 否 | 工人列表（supervisor） |
| `timeout` | 否 | 各阶段超时秒数 |
| `session_id` | 否 | 会话隔离：同一 session_id 共享独立的 agent 注册表与对话记忆 |
| `budget` | 否 | 运行预算 `{max_calls, max_tokens, max_cost, max_seconds}`，超预算立即中止 |
| `context` | 否 | `{"window", "max_chars", "hide_own"}` 上下文压缩配置 |
| `cache` | 否 | bool，本次运行启用/停用 LLM 响应缓存 |

```bash
curl -s -X POST localhost:8000/run -H "Content-Type: application/json" -d \
  '{"type": "run", "prompt": "你好", "strategy": "debate", "rounds": 1}'
```

成功（200）响应：

```json
{
  "strategy": "debate",
  "prompt": "你好",
  "rounds": [
    { "round": 1, "kind": "debate", "responses": { "alpha": "...", "beta": "..." } },
    { "step": "judge", "agent": "alpha", "response": "最终结论" }
  ],
  "final": "最终结论",
  "meta": { "elapsed_seconds": 1.2, "agents": ["alpha", "beta"], "strategy": "debate" }
}
```

错误响应：

| 状态码 | 场景 | 响应体示例 |
| --- | --- | --- |
| 400 | JSON 解析失败 / 事件不是对象 / 缺 prompt | `{"error": "invalid json: ..."}` 等 |
| 401 / 403 | 令牌缺失 / 权限不足 | `{"error": "unauthorized"}` / `{"error": "forbidden", "required_role": "user"}` |
| 500 | 执行时异常 | `{"error": "adapter error", "detail": "..."}` |

---

## 7. 运行 Trace（GET /runs、GET /runs/{id}）

每次 `/run` 会在有界的 RunRegistry 中留下一份 Trace（span 与任务记录）：

```bash
curl -s localhost:8000/runs              # 最近运行的摘要列表
curl -s localhost:8000/runs/<run_id>     # 单次运行的完整 Trace（404 表示已被清理或不存在）
```

registry 有容量与 TTL 上限，长期运行不会无限增长。

---

## 8. 会话管理（/sessions）

启动带 `--session-ttl` / `--max-sessions` 时生效：

```bash
curl -s localhost:8000/sessions                  # 统计（顺带清理过期会话）
curl -s -X POST localhost:8000/sessions/cleanup  # 强制清理，返回被清退的 id
curl -s -X DELETE localhost:8000/sessions/task-42
```

---

## 9. POST /register

运行中动态注册 Agent：

```json
{
  "type": "register",
  "agents": [
    { "name": "w1", "kind": "echo" },
    { "name": "analyst", "kind": "deepseek", "model": "deepseek-chat" }
  ]
}
```

```bash
curl -s -X POST localhost:8000/register -H "Content-Type: application/json" -d \
  '{"type": "register", "agents": [{"name": "w1", "kind": "echo"}]}'
```

响应：

```json
{ "registered": ["w1", "analyst"] }
```

Agent 字段与配置文件的 `agents` 段一致（见 [usage.md](usage.md) 第 3 节）。

---

## 10. 事件协议（供 Harness / 其他客户端复用）

`/run` 与 `/register` 的请求体即 `DeepseekAdapter.handle_harness_event` 支持的事件。
除 `run`、`register` 外，还支持：

| 事件 | 请求 | 响应 |
| --- | --- | --- |
| `status` | `{"type": "status"}` | `{"status": "ok", "agents": [...], "strategy": ...}` |
| `agents` | `{"type": "agents"}` | `{"agents": [...]}` |
| `history` | `{"type": "history", "limit": 10}` | `{"records": [...]}`（最新在前；未启用时 `{"records": [], "enabled": false}`） |

```bash
curl -s -X POST localhost:8000/run -H "Content-Type: application/json" -d '{"type": "status"}'
```

---

## 11. 安全建议

- 服务默认只监听 `127.0.0.1`；对外暴露时配置令牌鉴权（见第 2 节），公网部署再置于
  反向代理（Nginx/Caddy）后面终结 TLS；
- `base_url` 可指向任意地址——如果代理了外部请求，注意防止 SSRF 类滥用；
- `--config` 中的 `api_key` 建议用环境变量（`DEEPSEEK_API_KEY` / `OPENAI_API_KEY`）代替明文。

## 12. 与 Harness 工作流对接示例

```python
import json
from urllib import request

def call_plugin(prompt, strategy="supervisor", rounds=3, port=8000, token=None):
    payload = json.dumps({
        "type": "run",
        "prompt": prompt,
        "strategy": strategy,
        "rounds": rounds,
    }).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(
        f"http://127.0.0.1:{port}/run",
        data=payload,
        headers=headers,
    )
    with request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode())

result = call_plugin("写一份校园社团招新方案")
print(result["final"])
```
---

## 13. 运行历史持久化（GET /history）

启动时指定 `--history FILE`（或环境变量 `DS_HISTORY_FILE`）后：

- 每次 `POST /run` 成功执行都会自动把结果摘要追加到该 JSONL 文件
  （失败不记录），字段包括 `strategy`、`prompt`、`final`、`rounds`（轮数）、
  `session_id`、`elapsed_seconds`、`index`（自增序号）与 `timestamp`；
- `GET /history?limit=N` 返回最近 N 条记录（倒序，最新在前），默认 20；
- `GET /health` 附加 `"history": "on"` 与当前记录条数 `history_count`；
- 未启用时 `GET /history` 返回 `{"records": [], "enabled": false}`。

```bash
python -m deepseek_multi_agent_plugin.adapters.http --port 8000 --demo --history runs.jsonl
curl -s "localhost:8000/history?limit=5"
```
