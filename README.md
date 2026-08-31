# DHS-multi-agent-plugin

[![CI](https://github.com/Li3NGa/deepseek-multi-agent-plugin/actions/workflows/ci.yml/badge.svg)](https://github.com/Li3NGa/deepseek-multi-agent-plugin/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/deepseek-multi-agent-plugin.svg)](https://pypi.org/project/deepseek-multi-agent-plugin/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)

多智能体协同运行时 / Multi-agent orchestration runtime：定义一支 Agent 团队（DeepSeek、
OpenAI 兼容 LLM、HTTP 服务、外部 CLI 命令、纯 Python 逻辑或后备链），用结构化任务图
（DAG）与六种协作策略编排它们，通过 Python API、CLI、HTTP 或 MCP stdio 使用。

> 📚 详细文档：[使用指南](docs/usage.md) · [策略详解](docs/strategies.md) ·
> [API 参考](docs/api_reference.md) · [HTTP 接口](docs/http_api.md) ·
> [MCP 服务器](docs/mcp.md) · [部署指南](docs/deployment.md) · [示例代码](examples/)

## Overview

本项目提供一个多智能体运行时：注册一组 Agent，提交一个 prompt，运行时负责调度、
并发、超时、预算与记忆，返回带完整过程记录的结果。核心分层：

```
┌────────────────────────────────────────────────────────────┐
│ adapters/          传输层（不侵入核心）                    │
│   cli.py · http.py（RBAC 鉴权）· mcp.py（stdio JSON-RPC）  │
└──────────────────────────┬─────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│ AgentCoordinator   Agent 注册表 + 策略分发 + run 入口       │
├────────────────────────────────────────────────────────────┤
│ strategies.py      broadcast / sequential / debate /       │
│                    supervisor / consensus / relay          │
│ supervisor.py      结构化 TaskPlan + capability 路由       │
│ runtime/           task.py DAG 引擎 · scheduler.py 调度器  │
│                    executor.py 共享有界线程池              │
│                    budget.py 预算 · deadline.py 运行截止   │
├────────────────────────────────────────────────────────────┤
│ agents.py          mock / echo / http / cli / custom /     │
│                    deepseek / openai / fallback（后备链）  │
├────────────────────────────────────────────────────────────┤
│ memory · context · cache · sessions · observability ·      │
│ history · security · config                                │
└────────────────────────────────────────────────────────────┘
```

- 核心层（coordinator/strategies/runtime/agents）不依赖任何传输层；
  HTTP、MCP、CLI 全部位于 `adapters/`，旧模块路径（`adapter_server.py` 等）
  保留为兼容别名。
- LLM 调用只依赖标准库（OpenAI 兼容 `/chat/completions` 协议），整个包
  零运行时依赖（YAML 配置可选安装 PyYAML）。

## Features

- **6 种协作策略**：broadcast（并行讨论）、sequential（流水线）、debate（多轮辩论 + 裁判）、
  supervisor（任务分解 + 并行执行）、consensus（提案-投票）、relay（接力打磨）。
- **结构化任务图**：supervisor 输出 JSON TaskPlan（`tasks[].id/description/agent/depends_on`），
  由 DAG 调度器执行——无依赖的任务并行，有依赖的任务等待，支持
  `PENDING/RUNNING/SUCCESS/FAILED/TIMEOUT/CANCELLED/SKIPPED` 状态。
- **Agent 能力（capabilities）**：按任务需求匹配 agent 能力路由，而非简单轮转。
- **后备链（FallbackAgent）**：`FallbackAgent("name", [primary, backup])` 在
  provider 失败时切换备用 agent / 备用 provider，用量照常计入预算。
- **预算控制**：`budget={"max_calls", "max_tokens", "max_cost", "max_seconds"}`，
  每次 agent 调用前预留额度，超预算立即中止，防止 supervisor/辩论/重试组合失控。
- **统一并发模型**：全进程共享一个有界线程池（`DSMA_MAX_CONCURRENCY`，默认 16），
  per-agent 超时 + 运行级 deadline（`run_timeout`），超时任务取消不再无限等待。
  池带饱和门卫：`submit` 最多等待 `DSMA_POOL_SLOT_TIMEOUT`（默认 1s）获取空闲
  worker，池满时快速失败（`PoolSaturated` → 按超时降级），慢 worker 身后不会无限排队。
  HTTP/MCP 入口另有并发 run 限流（`--max-runs`，默认 4）：同时在跑的 run 超限时
  快速失败并返回 HTTP 429，保护线程池与上游 LLM 配额。
- **会话生命周期**：`session_id` 隔离注册表与记忆；TTL 过期、容量上限、LRU 淘汰、
  统计与清理端点，长期运行不会内存膨胀。
- **响应缓存**：对 model/messages/temperature/… 全参数做指纹的 LRU 缓存，
  支持 TTL 与命中统计，不同请求不会错误命中。
- **可观测性**：每次 run 生成 Trace（span/task），有界 RunRegistry，
  `GET /runs`、`GET /runs/{id}`、`GET /status` 与 MCP `runs`/`status` 工具回查。
- **HTTP 安全基线**：readonly / user / operator / admin 四级角色 RBAC，端点按最低
  角色鉴权；日志与错误栈自动脱敏；`Content-Length` 负值 / 冲突 / 畸形一律 400（防
  请求走私与慢速 DoS）；`POST` 强制 `Content-Type: application/json`（缓解跨站
  simple-request CSRF）；`Server` 响应头隐藏 Python 版本指纹；`$DS_AGENT_ROLES`
  空 token 拒绝启动。
- **四种使用方式**：Python API、CLI（`deepseek-multi-agent`）、HTTP 适配服务、MCP stdio 服务。

## Installation

```bash
pip install deepseek-multi-agent-plugin
# 可选：YAML 配置支持
pip install "deepseek-multi-agent-plugin[dev]"   # 含 pytest / ruff / pyyaml
```

要求 Python 3.10+。零运行时依赖。

## Quick Start

```bash
# 两个内置 mock agent 跑一场辩论，无需 API Key
deepseek-multi-agent run --demo --strategy debate --rounds 2 \
  --prompt "AI 安全当前最重要的问题是什么？"

# 使用 YAML 配置的 DeepSeek 团队（需要 DEEPSEEK_API_KEY）
deepseek-multi-agent run --config example_config.yaml --strategy supervisor \
  --prompt "为校园社团设计一个招新方案"

# 启动 HTTP 适配服务
deepseek-multi-agent serve --config example_config.yaml --port 8000
```

Python API：

```python
from deepseek_multi_agent_plugin import AgentCoordinator, AgentFactory

coord = AgentCoordinator()
coord.register_agent(AgentFactory.create_agent('deepseek', 'researcher',
    system_prompt='你是一名严谨的研究员'))
coord.register_agent(AgentFactory.create_agent('deepseek', 'critic',
    system_prompt='你是一名挑剔的批评家'))

# 跑一场 2 轮辩论，并限制整个 run 最多 20 次调用、60 秒
result = coord.run("AI 安全最重要的问题是什么？", strategy="debate", rounds=2,
                   budget={"max_calls": 20, "max_seconds": 60})
print(result["final"])     # 裁判的最终结论
print(result["rounds"])    # 完整过程记录
print(result["meta"]["usage"])  # token 用量汇总
```

## Configuration

`example_config.yaml`（本项目根目录）演示了一个由 DeepSeek 支撑的三人辩论团队：

```yaml
coordinator:
  strategy: debate
  rounds: 3
  timeout_seconds: 30
  # budget:            # 每次 run 的默认预算（可被 run(budget=...) 覆盖）
  #   max_calls: 20
  #   max_tokens: 100000
agents:
  - name: researcher
    kind: deepseek
    role: 研究员
    system_prompt: 你是一名严谨的研究员，擅长收集信息并给出有依据的分析。
    temperature: 0.3
    capabilities: research,analysis     # supervisor 按能力路由任务
  - name: critic
    kind: deepseek
    role: 批评家
    system_prompt: 你是一名挑剔的批评家，善于发现方案中的漏洞与风险。
    temperature: 0.7
    capabilities: critique
  - name: judge
    kind: deepseek
    role: 裁判
    system_prompt: 你是一名公正的裁判，会综合各方观点给出最终结论。
    temperature: 0.2
```

也可以从代码构建：`build_coordinator(path="example_config.yaml")`。

## Agents

| kind | 说明 | 必需参数 |
| --- | --- | --- |
| `mock` | 模板回复，支持 `{msg}`、`{name}` | `message_template`（可选） |
| `echo` | 回显 `{name} echo: {msg}` | 无 |
| `http` | 向 `url` POST JSON `{"message": msg}` 并解析响应 | `url` |
| `deepseek` | DeepSeek 官方 API | `api_key` 或 `DEEPSEEK_API_KEY` |
| `openai` | 任意 OpenAI 兼容端点 | `api_key` 或 `OPENAI_API_KEY` |
| `custom` | 任意 Python 可调用对象 | `handler` |
| `cli` | 外部命令行程序，消息作为最后一个参数 | `command` |
| `fallback` | 后备链：按顺序尝试 `backends` 中的 agent，首个成功者生效 | `backends`（Agent 列表） |

LLM agent 还支持 `role`、`system_prompt`、`model`、`temperature`、`max_tokens`、
`base_url`、`retries`、`capabilities`。LLM 调用对 429/5xx/连接错误做指数退避重试
（尊重 `Retry-After`），重试耗尽后抛出异常、由策略层按 agent 隔离记录。

`FallbackAgent` 示例（provider 宕机时切换到备用 provider）：

```python
from deepseek_multi_agent_plugin import Agent, AgentFactory, FallbackAgent

primary = AgentFactory.create_agent('deepseek', 'ds-primary', api_key='...')
backup = AgentFactory.create_agent('openai', 'oa-backup', api_key='...')
coord.register_agent(FallbackAgent('writer', [primary, backup]))
```

## Strategies

| 策略 | 说明 | 适用场景 |
| --- | --- | --- |
| `broadcast` | 所有 agent 并行回答；`rounds>1` 时把上一轮回答汇总作为下一轮输入 | 头脑风暴、观点收集 |
| `sequential` | 按指定顺序逐个发言，每个 agent 看到完整历史 | 流水线：分析→设计→实现→评审 |
| `debate` | 多轮辩论，最后裁判综合所有观点 | 需要对抗与收敛的决策 |
| `supervisor` | 分解任务为结构化子任务，DAG 调度并行执行，汇总成报告 | 复杂任务拆解与并行 |
| `consensus` | 每个 agent 提案，全员投票，平票由裁判裁决 | 需要多数共识的选择题 |
| `relay` | 轮流打磨同一份草稿，无变化时提前收敛 | 初稿→润色→审校 |

策略名也可用 `auto`：1 个 agent 时选 `broadcast`，存在名为 `supervisor` 的 agent 时
选 `supervisor`，否则选 `debate`。

## Task Engine

supervisor 策略不再依赖文本拆分：LLM 被要求输出结构化 JSON 计划，

```json
{"tasks": [
  {"id": "task_1", "description": "收集资料", "agent": "researcher", "depends_on": []},
  {"id": "task_2", "description": "风险分析", "agent": "critic",    "depends_on": ["task_1"]}
]}
```

`runtime/task.py` + `runtime/scheduler.py` 按 DAG 执行：`A → B`、`A → C`、
`B,C → D` 菱形依赖会被正确调度，无依赖的任务并行执行。计划损坏
（环依赖、未知依赖、重复 id、非 JSON 输出）会被自动恢复为保守的可行计划并记录 note。
运行级 deadline 或预算耗尽时，未开始的 task 标记 `CANCELLED`，已完成的保留结果。

## Sessions

事件可携带 `session_id`：每个会话获得独立的 agent 注册表与对话记忆，并发任务互不污染。
`SessionManager` 提供 TTL 过期、`max_sessions` 容量上限（LRU 淘汰）与统计：

```bash
python -m deepseek_multi_agent_plugin.adapters.http --port 8000 --demo \
  --session-ttl 900 --max-sessions 100

curl -s localhost:8000/sessions                 # 统计（顺带清理过期会话）
curl -s -X POST localhost:8000/sessions/cleanup # 强制清理，返回被清退的 id
curl -s -X DELETE localhost:8000/sessions/task-42
```

## HTTP

```bash
python -m deepseek_multi_agent_plugin.adapters.http --port 8000 --demo
# 旧路径 python -m deepseek_multi_agent_plugin.adapter_server 仍然可用
```

| 端点 | 方法 | 最低角色 | 说明 |
| --- | --- | --- | --- |
| `/health` | GET | readonly | 健康检查 |
| `/agents` | GET | readonly | 列出已注册 agent |
| `/status` | GET | readonly | 版本 + agent 健康计数 + 运行数 |
| `/run` | POST | user | 执行协作任务 |
| `/runs` | GET | operator | 最近运行 Trace 摘要 |
| `/runs/{id}` | GET | operator | 单次运行完整 Trace |
| `/history` | GET | operator | 运行历史（`--history` 启用） |
| `/sessions` | GET | operator | 会话统计 |
| `/sessions/cleanup` | POST | operator | 强制清理过期会话 |
| `/sessions/{id}` | DELETE | operator | 删除会话 |
| `/register` | POST | admin | 动态注册 agent |

鉴权（不配置即本地开放模式）：

```bash
# 单令牌 = admin（与旧版 --token 行为一致）
python -m ... --token s3cret          # 或环境变量 DS_AGENT_TOKEN

# 分角色令牌（可重复，或 $DS_AGENT_ROLES 传 JSON 对象）
python -m ... --role readonly:ro-token --role user:u-token \
             --role operator:op-token --role admin:ad-token
```

角色层级：readonly < user < operator < admin。请求需带
`Authorization: Bearer <token>`；权限不足返回 403 并指明所需角色。
服务端日志与异常栈在落盘前做凭据脱敏。

## MCP

```bash
python -m deepseek_multi_agent_plugin.adapters.mcp --config example_config.yaml
# 旧路径 python -m deepseek_multi_agent_plugin.mcp_server 仍然可用
```

通过 stdio JSON-RPC 暴露 `run` / `agents` / `register` / `status` / `history` / `runs`
工具给 DSH、Codex、Claude Code 等 MCP 宿主。MCP 服务由宿主进程拉起、继承宿主自身的
访问控制，因此不做 HTTP 那套令牌鉴权。详见 [docs/mcp.md](docs/mcp.md)。

## Development

```bash
git clone https://github.com/Li3NGa/deepseek-multi-agent-plugin
cd deepseek-multi-agent-plugin
pip install -e ".[dev]"
```

常用命令：

```bash
pytest -q          # 全部测试
ruff check src tests
```

## Testing

- 344 个测试：单元（agents / strategies / task engine / sessions / memory /
  cache / budget / security）、集成（HTTP / MCP / CLI / e2e）、并发与失败注入
  （429、5xx、连接重置、畸形响应、重试耗尽、100 会话 × 10 agent 压力、池饱和、
  并发 run 限流、HTTP 请求走私 / CSRF / 认证绕过回归）。
- GitHub Actions 在 Python 3.10–3.13 矩阵上运行测试 + ruff + mypy + 构建 + 冒烟。

## Contributing

欢迎 issue 与 PR：改动请附带测试；提交信息用简短祈使句（如 `add session ttl eviction`）；
发布流程见 [docs/publishing.md](docs/publishing.md)。

## License

MIT License. See [LICENSE](LICENSE).
