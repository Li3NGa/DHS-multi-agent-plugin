# HTTP 服务接口（HTTP Adapter API）

适配服务把插件的全部能力暴露为 HTTP JSON 接口，方便 DeepSeek Harness、脚本、其他服务调用。
服务仅用 Python 标准库实现（`http.server`），无额外依赖。

> 上一级：[详细使用说明](usage.md)

---

## 1. 启动

```bash
# 方式一：模块启动（推荐）
python -m deepseek_multi_agent_plugin.adapter_server --port 8000 --demo

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

---

## 2. 端点总览

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/health` | GET | 健康检查 |
| `/agents` | GET | 列出已注册 Agent |
| `/run` | POST | 执行一次协作任务 |
| `/register` | POST | 动态注册 Agent（运行中扩员） |
| `/history` | GET | 查询最近运行历史（需 `--history` 启动） |

所有响应均为 JSON（`application/json; charset=utf-8`）。

---

## 3. GET /health

```bash
curl -s localhost:8000/health
```

```json
{ "status": "ok" }
```

---

## 4. GET /agents

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

## 5. POST /run

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
  "timeout": 30
}
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `type` | 是 | 固定为 `"run"` |
| `prompt` | 是 | 任务提示词；缺失返回 400 `{"error": "missing prompt"}` |
| `strategy` | 否 | `auto`（默认）/ `broadcast` / `sequential` / `debate` / `supervisor` / `consensus` |
| `rounds` | 否 | 轮数（broadcast/debate） |
| `judge` | 否 | 裁判 Agent 名（debate/consensus） |
| `order` | 否 | 顺序列表（sequential） |
| `workers` | 否 | 工人列表（supervisor） |
| `timeout` | 否 | 各阶段超时秒数 |

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
| 500 | 执行时异常 | `{"error": "adapter error", "detail": "..."}` |

---

## 6. POST /register

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

## 7. 事件协议（供 Harness / 其他客户端复用）

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

## 8. 安全建议

- 服务默认只监听 `127.0.0.1`，无鉴权、无 TLS；
- 对外暴露时请置于反向代理之后（Nginx/Caddy + Basic Auth 或 mTLS）；
- `base_url` 可指向任意地址——如果代理了外部请求，注意防止 SSRF 类滥用；
- `--config` 中的 `api_key` 建议用环境变量（`DEEPSEEK_API_KEY` / `OPENAI_API_KEY`）代替明文。

## 9. 与 Harness 工作流对接示例

```python
import json
from urllib import request

def call_plugin(prompt, strategy="supervisor", rounds=3, port=8000):
    payload = json.dumps({
        "type": "run",
        "prompt": prompt,
        "strategy": strategy,
        "rounds": rounds,
    }).encode()
    req = request.Request(
        f"http://127.0.0.1:{port}/run",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode())

result = call_plugin("写一份校园社团招新方案")
print(result["final"])
```
---

## 10. 运行历史持久化（GET /history）

启动时指定 `--history FILE`（或环境变量 `DS_HISTORY_FILE`）后：

- 每次 `POST /run` 成功执行都会自动把结果摘要追加到该 JSONL 文件
  （失败不记录），字段包括 `strategy`、`prompt`、`final`、`rounds`（轮数）、
  `session_id`、`elapsed_seconds`、`index`（自增序号）与 `timestamp`；
- `GET /history?limit=N` 返回最近 N 条记录（倒序，最新在前），默认 20；
- `GET /health` 附加 `"history": "on"` 与当前记录条数 `history_count`；
- 未启用时 `GET /history` 返回 `{"records": [], "enabled": false}`。

```bash
python -m deepseek_multi_agent_plugin.adapter_server --port 8000 --demo --history runs.jsonl
curl -s "localhost:8000/history?limit=5"
```
