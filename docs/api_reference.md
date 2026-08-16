# Python API 参考（API Reference）

本文档列出 `deepseek_multi_agent_plugin` 公开 API 的完整签名、参数与返回值。
包版本：`__version__ = "0.2.0"`。

> 上一级：[详细使用说明](usage.md)

---

## 包级导出

```python
from deepseek_multi_agent_plugin import (
    Agent, AgentCoordinator, AgentFactory, DeepseekAdapter,
    MessageStore, build_coordinator, chat_completion, load_config,
    strategies, __version__,
)
```

---

## 1. Agent

```python
Agent(
    name: str,
    handler: Callable[[Any], Any] | None = None,
    *,
    role: str | None = None,
    system_prompt: str | None = None,
    provider: str | None = None,          # "deepseek" | "openai"
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    memory: MessageStore | None = None,
    timeout: float = 60.0,                # 单次 LLM 调用超时（秒）
)
```

一个 Agent 必须有且仅有一种后端：`handler` 可调用对象，或 `provider` LLM 服务。

### 方法

| 方法 | 说明 |
| --- | --- |
| `handle(message, context=None)` | 处理一条消息并返回响应。`context` 为可选的 OpenAI chat 格式消息列表，会插入到当前消息之前（策略用它传递讨论历史） |
| `chat(messages)` | 直接以完整 chat 消息列表调用 LLM（会前置 `system_prompt`），仅 provider Agent 可用 |
| `describe()` | 返回 `{"name", "role", "provider", "model", "has_handler"}` |

### 错误约定

- `provider` 未知 → `ValueError`；
- 既无 `handler` 又无 `provider` 就调用 → `RuntimeError`；
- LLM 调用缺少 API Key → `RuntimeError`（提示设置对应环境变量或 `api_key` 参数）。

### 环境变量

| provider | 环境变量 | 默认模型 | 默认 base_url |
| --- | --- | --- | --- |
| `deepseek` | `DEEPSEEK_API_KEY` | `deepseek-chat` | `https://api.deepseek.com` |
| `openai` | `OPENAI_API_KEY` | `gpt-4o-mini` | `https://api.openai.com/v1` |

---

## 2. AgentFactory

```python
AgentFactory.create_agent(kind: str, name: str, **kwargs) -> Agent
AgentFactory.from_config(cfg: dict) -> Agent
AgentFactory.from_configs(configs: list[dict]) -> list[Agent]
```

### kind 与 kwargs

| kind | kwargs | 说明 |
| --- | --- | --- |
| `mock` | `message_template`（默认 `{msg}`，支持 `{msg}` `{name}`） | 模板回复 |
| `echo` | — | 返回 `{name} echo: {msg}` |
| `http` | `url`（必填）、`timeout`（默认 5） | POST `{"message": msg}` 到端点，返回解析后的 JSON 或文本 |
| `deepseek` / `openai` | `role`、`system_prompt`、`model`、`temperature`、`max_tokens`、`api_key`、`base_url`、`timeout` | LLM Agent |
| `custom` | `handler`（必填，可调用对象） | 任意 Python 逻辑 |
| `cli` | `command`（必填）、`args`（默认 `[]`）、`timeout`（默认 300）、`cwd`、`encoding`（默认 `utf-8`） | 调用外部命令行 agent，消息作为最后一个参数传入 |

`from_config` 中省略 `kind` 时：提供 `handler` 视为 `custom`，否则视为 `mock`。
未知 kind → `ValueError`。

---

## 3. MessageStore（共享记忆）

```python
MessageStore(capacity: int | None = None)
```

线程安全的追加式消息缓冲，`capacity` 限制最大条数（超出丢弃最旧）。

| 方法 | 说明 |
| --- | --- |
| `add(role, content, agent=None, **meta)` | 追加一条消息（`role` 为 `user`/`assistant`/`system`），返回该消息 dict |
| `all()` | 全部消息列表 |
| `recent(n)` | 最近 n 条 |
| `clear()` | 清空 |
| `to_chat(limit=None)` | 投影为 OpenAI chat 格式 `[{role, content}]` |
| `len(store)` | 消息条数 |

---

## 4. AgentCoordinator

```python
AgentCoordinator(memory: MessageStore | None = None, timeout: float = 15.0)
```

### 注册管理

| 方法 / 属性 | 说明 |
| --- | --- |
| `register_agent(agent, replace=True)` | 注册 Agent；`replace=False` 且重名时抛 `ValueError` |
| `unregister_agent(name)` | 注销（不存在时静默） |
| `get_agent(name)` | 按名取 Agent，未注册返回 `None` |
| `agents` | 按注册顺序的 Agent 列表 |
| `agent_names` | Agent 名列表 |

### 执行

```python
run(prompt: str, strategy: str = "auto", **kwargs) -> dict
```

- `strategy`：`auto` / `broadcast` / `sequential` / `debate` / `supervisor` / `consensus` / `relay`；
  未知策略 → `ValueError`；没有注册任何 Agent → `RuntimeError`。
- `**kwargs` 按策略签名过滤后转发（见 [strategies.md](strategies.md)），不认识的参数被忽略。
- 返回统一结果结构：`{"strategy", "prompt", "rounds", "final", "meta"}`。

### 兼容旧 API

| 方法 | 说明 |
| --- | --- |
| `broadcast(message, timeout=None)` | 单轮并行广播，返回 `{agent名: 响应}` |
| `run_cooperative_task(initial_prompt, rounds=3)` | 等价于 `run(..., strategy="broadcast")`，返回轮次列表 |

---

## 5. 策略函数（strategies 模块）

```python
from deepseek_multi_agent_plugin import strategies

strategies.run_broadcast(coord, prompt, rounds=1, timeout=None)
strategies.run_sequential(coord, prompt, order=None, timeout=None)
strategies.run_debate(coord, prompt, rounds=3, judge=None, timeout=None)
strategies.run_supervisor(coord, prompt, supervisor=None, workers=None, timeout=None)
strategies.run_consensus(coord, prompt, judge=None, timeout=None)
strategies.run_relay(coord, prompt, rounds=2, order=None, timeout=None)

strategies.run_strategy(coord, strategy, prompt, **kwargs)  # 通用分发
strategies.STRATEGIES                              # 名称 -> 函数 的字典
```

各策略的流程、参数、限制（最少 Agent 数等）见 [协作策略详解](strategies.md)。

---

## 6. 配置（config 模块）

```python
load_config(path: str) -> dict
build_coordinator(config: dict | None = None, *, path: str | None = None) -> AgentCoordinator
```

- `load_config` 支持 `.yaml` / `.yml`（需 PyYAML）/ `.json`；其他扩展名 → `ValueError`。
- `build_coordinator` 从配置构建协调器：注册 `agents` 段的所有 Agent，并把 `coordinator.timeout_seconds`
  作为协调器默认超时。

配置结构：

```yaml
coordinator:
  timeout_seconds: 15
agents:
  - name: a1
    kind: mock
    message_template: "你好 {msg}"
```

---

## 7. DeepseekAdapter（Harness 事件翻译）

```python
DeepseekAdapter(coordinator: AgentCoordinator, registry=None, history: RunHistory | None = None)
adapter.handle_harness_event(event: dict) -> dict
```

| 事件类型 | 请求 | 返回 |
| --- | --- | --- |
| `run` | `{"type": "run", "prompt", "strategy", "rounds", "judge", "order", "workers", "timeout"}` | 统一结果结构；缺 `prompt` 返回 `{"error": "missing prompt"}` |
| `agents` | `{"type": "agents"}` | `{"agents": [describe()...]}` |
| `status` | `{"type": "status"}` | `{"status": "ok", "agents": [...], "strategy": ...}` |
| `register` | `{"type": "register", "agents": [配置dict...]}` | `{"registered": [名字...]}` |
| `history` | `{"type": "history", "limit": 10}` | `{"records": [...]}`（未启用时 `{"records": [], "enabled": false}`） |
| 其他 | — | `{"error": "unsupported event type: ..."}` |

---

## 8. 底层工具

```python
chat_completion(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],            # OpenAI chat 格式
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float = 60.0,
) -> str
```

对 `POST {base_url}/chat/completions` 的纯标准库封装，返回首个 `choices[0].message.content`；
响应结构异常时返回整个响应的 JSON 字符串（便于排查）。

## 9. adapter_server 模块

```python
serve(host: str, port: int, coordinator: AgentCoordinator) -> None
register_demo_agents(coordinator) -> None      # 注册 alpha / beta 两个 mock Agent
main(argv=None) -> None                        # argparse 入口：--host --port --config --demo
```

服务端点协议见 [HTTP 服务接口](http_api.md)。
---

## 10. RunHistory（运行历史，history 模块）

```python
from deepseek_multi_agent_plugin import RunHistory

h = RunHistory("runs.jsonl")        # 文件不存在时自动创建（含父目录）
h.append({"strategy": "debate", "prompt": "你好", "final": "..."})
                                    # 自动补充自增 index 与 ISO 8601 本地时间 timestamp
h.recent(limit=20)                  # 最近 20 条，倒序（最新在前）
len(h)                              # 记录条数
h.clear()                           # 清空文件并重置序号
```

- 追加与读取共用一把锁，多线程并发 `append` 不会丢记录；
- 记录字段由调用方决定；`DeepseekAdapter` 在 `run` 事件成功后自动写入
  摘要（`strategy` / `prompt` / `final` / `rounds` / `session_id` /
  `elapsed_seconds`），失败不记录；
- 通过 `DeepseekAdapter(coord, history=h)`、HTTP `--history FILE` 或 MCP
  `--history FILE` 启用。
