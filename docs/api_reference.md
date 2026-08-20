# Python API 参考（API Reference）

本文档列出 `deepseek_multi_agent_plugin` 公开 API 的完整签名、参数与返回值。
包版本：`__version__ = "1.0.1"`。

> 上一级：[详细使用说明](usage.md)

---

## 包级导出

```python
from deepseek_multi_agent_plugin import (
    # agents
    Agent, AgentFactory, FallbackAgent, ResponseCache, chat_completion,
    # coordination
    AgentCoordinator, DeepseekAdapter, build_coordinator, load_config,
    # memory / context
    MessageStore, ContextPolicy, build_context, truncate,
    # runtime
    BudgetManager,
    # lifecycle & observability
    SessionManager, RunRegistry, Span, Task, Trace,
    # errors
    DSMAError, AgentError, AgentNotFound, BudgetExceeded, PlanError,
    ProviderError, SessionNotFound, StrategyError, TaskError,
    # misc
    request_fingerprint, strategies, __version__,
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
    retries: int = 2,                    # 429/5xx 等瞬时故障的重试次数（默认 2）
    memory: MessageStore | None = None,
    timeout: float = 60.0,                # 单次 LLM 调用超时（秒）
    cache: bool = False,                  # 启用进程内响应缓存（自带 ResponseCache）
    capabilities: Iterable[str] | None = None,   # 能力标签，supervisor 按此路由
)
```

一个 Agent 必须有且仅有一种后端：`handler` 可调用对象，或 `provider` LLM 服务。

### FallbackAgent

```python
FallbackAgent(name: str, backends: Sequence[Agent], role: str | None = None)
```

后备链 agent：按顺序调用 `backends`，首个返回成功结果的生效；后端抛异常或返回
`{"error": ...}` 时切下一个，全部失败抛 `AgentError`。`BudgetExceeded` 不被吞掉
（预算必须生效），获胜后端的用量并入自身 `total_usage`。`capabilities` 为全部后端
能力的并集。

### 方法

| 方法 | 说明 |
| --- | --- |
| `handle(message, context=None)` | 处理一条消息并返回响应。`context` 为可选的 OpenAI chat 格式消息列表，会插入到当前消息之前（策略用它传递讨论历史） |
| `chat(messages)` | 直接以完整 chat 消息列表调用 LLM（会前置 `system_prompt`），仅 provider Agent 可用 |
| `describe()` | 返回 `{"name", "role", "provider", "model", "has_handler", "capabilities", "total_usage", "cache", "cache_hits"}` |

`cache=True` 时 Agent 自带一个线程安全 LRU `ResponseCache`（默认 128 条、不过期），
对影响模型结果的全部请求参数做指纹（见第 12 节），命中直接返回缓存内容而不打 HTTP，
命中计数累计到 `cache_hits`。

### 错误约定

- `provider` 未知 → `ValueError`；
- 既无 `handler` 又无 `provider` 就调用 → `RuntimeError`；
- LLM 调用缺少 API Key → `RuntimeError`（提示设置对应环境变量或 `api_key` 参数）；
- 重试耗尽后抛 `ProviderError`，由策略层按 agent 隔离记录。

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
| `deepseek` / `openai` | `role`、`system_prompt`、`model`、`temperature`、`max_tokens`、`api_key`、`base_url`、`timeout`、`retries`（默认 2）、`cache`（默认 false）、`capabilities` | LLM Agent |
| `custom` | `handler`（必填，可调用对象） | 任意 Python 逻辑 |
| `cli` | `command`（必填）、`args`（默认 `[]`）、`timeout`（默认 300）、`cwd`、`encoding`（默认 `utf-8`） | 调用外部命令行 agent，消息作为最后一个参数传入 |
| `fallback` | `backends`（必填，Agent 列表） | 后备链 agent，按顺序尝试后端 |

`from_config` 中省略 `kind` 时：提供 `handler` 视为 `custom`，否则视为 `mock`。
未知 kind → `ValueError`。配置 dict 中的 `capabilities` 接受逗号分隔字符串或列表。

---

## 3. MessageStore（共享记忆）

```python
MessageStore(capacity: int | None = None, max_chars: int | None = None)
```

线程安全的追加式消息缓冲，两个独立上限防止长生命周期协调器内存无限增长：

- `capacity`：最大消息条数（超出丢弃最旧）；
- `max_chars`：全部消息的总字符预算（超预算时从最旧开始丢弃，最新一条始终保留）。

| 方法 | 说明 |
| --- | --- |
| `add(role, content, agent=None, **meta)` | 追加一条消息（`role` 为 `user`/`assistant`/`system`），返回该消息 dict |
| `all()` | 全部消息列表 |
| `recent(n)` | 最近 n 条 |
| `clear()` | 清空 |
| `to_chat(limit=None)` | 投影为 OpenAI chat 格式 `[{role, content}]` |
| `total_chars()` | 当前内容总字符数 |
| `len(store)` | 消息条数 |

`ContextPolicy` 控制每次请求 agent *看到* 什么；这两个上限控制 *存储* 什么。

---

## 4. AgentCoordinator

```python
AgentCoordinator(
    memory: MessageStore | None = None,
    timeout: float = 15.0,
    context_policy: ContextPolicy | None = None,
    cache: bool = False,
    budget: dict | None = None,      # 默认预算（max_calls/max_tokens/max_cost/max_seconds）
)
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
- `run()` 额外支持几个由协调器自己消费的开关：
  - `context`（`ContextPolicy` 实例或 `{"window", "max_chars", "hide_own"}` dict，
    覆盖本次运行的上下文策略）；
  - `cache`（bool，本次运行启用/停用 LLM 响应缓存）；
  - `budget`（dict 或 `BudgetManager`，本次运行的预算；缺省用构造器的 `budget` 默认值，
    见第 13 节）；
  - `run_timeout`（秒，整个 run 的运行级截止时间；到点后未开始的 agent 调用直接取消。
    等价于 `budget={"max_seconds": ...}`）。
- 返回统一结果结构：`{"strategy", "prompt", "rounds", "final", "meta"}`。
- `meta.usage` 汇总形状：`{"total": {prompt_tokens, completion_tokens, total_tokens},
  "agents": {agent名: {...}}, "cache_hits": N}`；带预算时另有 `meta.budget` 用量快照。

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
  作为协调器默认超时；`coordinator.context`（dict，含 `window` / `max_chars` / `hide_own`）
  解析为 `ContextPolicy`，`coordinator.cache`（bool）启用协调器级响应缓存，
  `coordinator.budget`（dict）作为每次 run 的默认预算。

配置结构：

```yaml
coordinator:
  timeout_seconds: 15
  context:
    window: 6
    max_chars: 2000
    hide_own: false
  cache: false
  budget:
    max_calls: 20
    max_seconds: 120
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
| `run` | `{"type": "run", "prompt", "strategy", "rounds", "judge", "order", "workers", "timeout", "context", "cache"}` | 统一结果结构；缺 `prompt` 返回 `{"error": "missing prompt"}`。`context` 为 `{"window", "max_chars", "hide_own"}` dict，`cache` 为 bool，均透传给 `coordinator.run()` |
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
    retries: int = 2,
    backoff: float = 0.5,
    response_format: dict | None = None,
    return_usage: bool = False,
    cache: ResponseCache | None = None,
) -> str
```

对 `POST {base_url}/chat/completions` 的纯标准库封装，返回首个 `choices[0].message.content`；
响应结构异常时返回整个响应的 JSON 字符串（便于排查）。
`return_usage=True` 时返回 `{"content", "usage"}`；`cache` 给定时命中直接返回
缓存内容（不发 HTTP），usage 标记为 `{"cache_hit": true}`，未命中则把成功响应写入缓存。

## 9. 适配器（adapters 包）

传输层适配器位于 `deepseek_multi_agent_plugin.adapters`，不侵入核心运行时；
旧模块路径（`adapter_server` / `mcp_server` / 顶层 `cli`）保留为兼容别名。

```python
# adapters.http（HTTP JSON 服务）
serve(host: str, port: int, coordinator: AgentCoordinator) -> None
register_demo_agents(coordinator) -> None      # 注册 alpha / beta 两个 mock Agent
main(argv=None) -> None                        # argparse 入口：--host --port --config --demo
                                               #   --token / --role（RBAC）
                                               #   --session-ttl / --max-sessions
                                               #   --history / --history-prompt-limit / --history-final-limit

# adapters.mcp（stdio JSON-RPC）
main(argv=None) -> None                        # --config / --demo / --history ...

# adapters.cli（deepseek-multi-agent 命令）
main(argv=None) -> None                        # run / agents / serve 子命令
```

服务端点协议见 [HTTP 服务接口](http_api.md)，MCP 工具见 [MCP 服务器](mcp.md)。
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

---

## 11. ContextPolicy（上下文压缩）

```python
ContextPolicy(
    window: int | None = None,        # 历史窗口：保留最近 N 条历史消息
    max_chars: int | None = None,     # 逐条截断：每条保留前 N 字符 + "…"
    hide_own_statements: bool = False # 辩论中隐藏辩手自己的旧发言
)
ContextPolicy.from_dict({"window": 6, "max_chars": 2000, "hide_own": True})
build_context(prompt, messages, policy, agent_name=None) -> list[dict]
truncate(text, max_chars) -> str
```

- `build_context` 把原始 prompt（role=user）永远放在首位，绝不截断/绝不被窗口丢弃；
  其余历史消息按 `window` / `max_chars` 处理；`hide_own_statements=True` 且给出
  `agent_name` 时过滤该 agent 自己之前的 assistant 发言（按消息的 `agent` 字段识别）。
- `truncate` 保留前 `max_chars` 个字符并追加省略号 `…`，是各策略瘦身输入共用的工具。
- 所有字段默认关闭；不传策略时策略层行为与旧版本完全一致。

---

## 12. ResponseCache（LLM 响应缓存）

```python
ResponseCache(maxsize: int = 128, ttl: float | None = None)
cache.get(key: str) -> str | None
cache.put(key: str, value: str) -> None
cache.stats() -> dict     # {"size", "maxsize", "ttl", "hits", "misses", "expired", "evictions"}
cache.clear() -> None
len(cache)
```

- 线程安全进程内 LRU（`OrderedDict` + `Lock`），超出 `maxsize` 淘汰最久未使用条目；
  `ttl` 给定时条目读取时惰性过期；
- 缓存 key 由 `request_fingerprint(**fields)` 生成——对 base_url / model / messages /
  temperature / max_tokens / response_format / tools / seed 等**所有影响模型结果的参数**
  做 sha256 指纹；transport 参数（timeout / retries / api_key）不参与指纹，
  因此不同请求不会错误命中同一缓存；
- 命中时不打 HTTP，`return_usage=True` 时 usage 标记为 `{"cache_hit": true}`；
- `Agent(cache=True)` 自带一个 `ResponseCache` 并累计 `cache_hits`；
  `AgentFactory.create_agent(..., cache=True)` 与配置 dict 的 `cache` 字段同样生效；
  `mock` / `echo` / `http` / `cli` / `custom` agent 不参与缓存。

---

## 13. BudgetManager（运行预算）

```python
from deepseek_multi_agent_plugin import BudgetManager

budget = BudgetManager(max_calls=20, max_tokens=100000, max_cost=0.5, max_seconds=120)
```

| 字段 | 说明 |
| --- | --- |
| `max_calls` | agent 调用次数上限（含在途调用） |
| `max_tokens` | prompt + completion token 总量上限 |
| `max_cost` | 成本上限（按 `pricer(usage)` 估算，可自定义计价函数） |
| `max_seconds` | run 时长上限，等效于 `run_timeout` |

- 协调器在每次 agent 调用前 `reserve()` 预留额度，调用完成后 `commit()` 实际用量，
  超预算抛 `BudgetExceeded`（立即中止剩余调用，已完成的结果保留）；
- `run(budget={"max_calls": ...})` 接受 dict 并自动转为 `BudgetManager`；
- `meta["budget"]` 携带本次 run 的预算用量快照。

## 14. SessionManager（会话生命周期）

```python
from deepseek_multi_agent_plugin import SessionManager

manager = SessionManager(factory=None, ttl=900.0, max_sessions=100)
```

`factory` 为返回新 `AgentCoordinator` 的可调用（缺省为无参构造）。方法：

| 方法 | 说明 |
| --- | --- |
| `get_or_create(session_id)` | 取会话协调器，不存在则创建；TTL 过期会话自动重建 |
| `get(session_id)` | 取会话协调器，不存在 / 过期返回 `None` |
| `delete(session_id)` | 删除会话，返回是否删除 |
| `cleanup()` | 清理全部过期会话，返回被清退的 id 列表 |
| `stats()` | 会话统计（数量、TTL、容量、最近活跃） |

容量满时创建新会话前按 LRU 淘汰最久未活跃的会话。`sessions.SessionRegistry` 是其
兼容别名（`adapters.http` 亦重新导出）。

## 15. Runtime（任务图与调度）

`deepseek_multi_agent_plugin.runtime` 包，supervisor 策略的执行层：

```python
from deepseek_multi_agent_plugin.runtime import Task, TaskPlan, TaskScheduler
from deepseek_multi_agent_plugin.runtime.task import TaskStatus
```

- `Task(id, description, agent=None, depends_on=(), required_capabilities=(), timeout=None)`：
  结构化子任务；
- `TaskPlan(tasks)`：任务集合，构造时校验重复 id、未知依赖、环依赖（抛 `PlanError`）；
- `TaskScheduler(run_task, default_timeout=None, deadline=None).execute(plan, on_event=None)`：
  DAG 执行——无依赖的任务并行（共享有界线程池），有依赖的任务等待；
  返回 `{task_id: TaskResult}`，`TaskResult.as_dict()` 含
  `task_id / status / agent / error / output / duration_ms`；
- `TaskStatus`：`PENDING` / `RUNNING` / `SUCCESS` / `FAILED` / `TIMEOUT` /
  `CANCELLED` / `SKIPPED`。

`supervisor.parse_plan(text, prompt, workers, agent_for)` 把主管 LLM 输出解析为
`(TaskPlan, info)`，JSON 与一行一任务两种格式都接受，损坏计划自动降级修复。

## 16. Observability（Trace / RunRegistry）

```python
from deepseek_multi_agent_plugin import RunRegistry, Trace, Span, Task
```

- 每次 `run()` 生成一个 `Trace`（`run_id` 唯一），内部记录 `Span`（agent 调用）
  与 `Task`（DAG 任务）；
- `AgentCoordinator.runs` 为有界 `RunRegistry`：容量与 TTL 上限，超限自动清理，
  长期运行不会内存膨胀；
- HTTP `GET /runs`、`GET /runs/{id}` 与 MCP `runs` 工具即对其的查询。

## 17. 异常模型（exceptions 模块）

```python
DSMAError                  # 基类
├── AgentError             # agent 执行失败（含 FallbackAgent 全后端失败）
├── AgentNotFound          # 引用未注册的 agent
├── StrategyError          # 策略前置条件不满足（如 debate 需要至少 2 个 agent）
├── ProviderError          # LLM provider 调用失败（重试耗尽后）
├── TaskError              # DAG 任务执行失败
├── PlanError              # 任务计划结构损坏（环依赖、重复 id 等）
├── BudgetExceeded         # 预算耗尽
└── SessionNotFound        # 引用不存在的会话
```

统一继承 `DSMAError`，调用方可按需捕获粒度；未归类错误仍为原生 Python 异常。

## 18. Security（RBAC）

```python
from deepseek_multi_agent_plugin.security import TokenAuthenticator, REQUIRED_ROLE

auth = TokenAuthenticator(roles={"readonly": "ro-token", "user": "u-token"})
role = auth.authenticate("Bearer ro-token")     # -> "readonly"（失败返回 None）
auth.allows(role, "run")                        # 该角色能否执行 run 动作
```

角色层级 `readonly < user < operator < admin`；`REQUIRED_ROLE` 映射动作 → 最低角色。
HTTP 适配器用其实现端点鉴权，MCP（宿主进程拉起、继承宿主访问控制）不使用。
