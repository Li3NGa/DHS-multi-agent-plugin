# deepseek-multi-agent-plugin

多智能体协同插件：定义一支 Agent 团队（DeepSeek / OpenAI 兼容 LLM、HTTP 服务或纯 Python 逻辑），
再用内置的协作策略（广播、流水线、辩论、主管-下属、共识投票）让它们一起完成任务。

A multi-agent collaboration plugin for the DeepSeek ecosystem: define a team of agents
(DeepSeek/OpenAI-compatible LLMs, HTTP services or plain Python handlers) and run them
together with built-in collaboration strategies: `broadcast`, `sequential`, `debate`,
`supervisor` and `consensus`.

[![CI](https://github.com/Li3NGa/deepseek-multi-agent-plugin/actions/workflows/ci.yml/badge.svg)](https://github.com/Li3NGa/deepseek-multi-agent-plugin/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](pyproject.toml)

---

## 特性 / Features

- **5 种开箱即用的协作策略**：广播讨论、顺序流水线（chain-of-agents）、多轮辩论（含裁判）、主管-下属（任务分解与并行执行）、提案-投票共识。
- **灵活的 Agent 定义**：`mock` / `echo` / `http` / `deepseek` / `openai` / `custom` 六种后端，LLM 调用仅依赖标准库（OpenAI 兼容 `/chat/completions` 协议）。
- **共享对话记忆**：所有策略共享一个线程安全的 `MessageStore`，每个 Agent 都能看到讨论全程。
- **健壮的并行执行**：每个阶段的超时与异常都按 Agent 捕获，不会让单个 Agent 拖垮整个协作。
- **三种使用方式**：Python API、命令行（`deepseek-multi-agent`）、HTTP 适配服务（可对接 DeepSeek Harness 等外部系统）。
- **零运行时依赖**（可选安装 PyYAML 以支持 YAML 配置），测试与 CI 完整。

## 架构 / Architecture

```
                      +-----------------------------+
                      |   AgentCoordinator          |
                      |   - agent registry          |
                      |   - shared MessageStore     |
                      |   - strategy dispatch       |
                      +-------------+---------------+
                                    |
              +---------------------+----------------------+
              |                    |                       |
      +-------v--------+  +--------v--------+   +---------v---------+
      |  strategies    |  |  Agent          |   |  DeepseekAdapter  |
      |  broadcast     |  |  - handler      |   |  HTTP /run events |
      |  sequential    |  |  - provider     |   |  CLI / server     |
      |  debate        |  |  - role/system  |   +---------+---------+
      |  supervisor    |  |  - memory       |             |
      |  consensus     |  +--------+--------+             |
      +-------+--------+           |                      |
              |                    |                      |
              v                    v                      v
        shared memory      DeepSeek/OpenAI HTTP      JSON over HTTP
                          or any callable backend   (harness integration)
```

## 快速开始 / Quickstart

```bash
# 安装（无需任何运行时依赖）
pip install deepseek-multi-agent-plugin

# 用两个内置 mock Agent 跑一场辩论，无需 API Key
deepseek-multi-agent run --demo --strategy debate --rounds 2 \
  --prompt "AI 安全当前最重要的问题是什么？"

# 完整 JSON 输出
deepseek-multi-agent run --demo --strategy consensus --json --prompt "帮我选个技术栈"

# 使用 YAML 配置的 DeepSeek 团队（需要 DEEPSEEK_API_KEY）
deepseek-multi-agent run --config example_config.yaml --strategy supervisor \
  --prompt "为校园社团设计一个招新方案"

# 启动 HTTP 适配服务
deepseek-multi-agent serve --config example_config.yaml --port 8000
```

## 协作策略 / Collaboration strategies

| 策略 | 说明 | 适用场景 |
| --- | --- | --- |
| `broadcast` | 所有 Agent 并行回答；`rounds>1` 时把上一轮回答汇总作为下一轮输入 | 头脑风暴、平行观点收集 |
| `sequential` | 按指定顺序逐个发言，每个 Agent 看到完整历史（chain-of-agents） | 流水线加工：分析→设计→实现→评审 |
| `debate` | 多轮辩论，最后裁判（judge）综合所有观点给出结论 | 需要对抗与收敛的决策、评审 |
| `supervisor` | 主管分解任务为子任务，工人并行执行，主管汇总成最终报告 | 复杂任务拆解与并行执行 |
| `consensus` | 每个 Agent 提案，全员投票，多数胜出；平票时由裁判裁决 | 需要多数共识的选择题 |

> 策略名也可用 `auto`：1 个 Agent 时自动选 `broadcast`，存在名为 `supervisor` 的 Agent 时选
> `supervisor`，否则选 `debate`。

## 定义 Agent / Defining agents

| kind | 说明 | 必需参数 |
| --- | --- | --- |
| `mock` | 模板回复，支持 `{msg}`、`{name}` | `message_template`（可选） |
| `echo` | 原样回显 `{name} echo: {msg}` | 无 |
| `http` | 向 `url` POST JSON `{"message": msg}` 并解析响应 | `url` |
| `deepseek` | DeepSeek 官方 API（OpenAI 兼容协议） | `api_key` 或环境变量 `DEEPSEEK_API_KEY` |
| `openai` | 任意 OpenAI 兼容端点 | `api_key` 或环境变量 `OPENAI_API_KEY` |
| `custom` | 任意 Python 可调用对象 | `handler` |

LLM Agent 还支持 `role`、`system_prompt`、`model`、`temperature`、`max_tokens`、`base_url` 等参数。

## 配置文件 / Configuration

`example_config.yaml`（本项目根目录）演示了一个由 DeepSeek 支撑的三人辩论团队：

```yaml
coordinator:
  strategy: debate
  rounds: 3
  timeout_seconds: 30
agents:
  - name: researcher
    kind: deepseek
    role: 研究员
    system_prompt: 你是一名严谨的研究员，擅长收集信息并给出有依据的分析。
    model: deepseek-chat
    temperature: 0.3
  - name: critic
    kind: deepseek
    role: 批评家
    system_prompt: 你是一名挑剔的批评家，善于发现方案中的漏洞与风险。
    model: deepseek-chat
    temperature: 0.7
  - name: judge
    kind: deepseek
    role: 裁判
    system_prompt: 你是一名公正的裁判，会综合各方观点给出最终结论。
    model: deepseek-chat
    temperature: 0.2
```

## Python API

```python
from deepseek_multi_agent_plugin import AgentCoordinator, AgentFactory

# 组建团队
coord = AgentCoordinator()
coord.register_agent(AgentFactory.create_agent('deepseek', 'researcher',
    system_prompt='你是一名严谨的研究员'))
coord.register_agent(AgentFactory.create_agent('deepseek', 'critic',
    system_prompt='你是一名挑剔的批评家'))

# 跑一场 2 轮辩论
result = coord.run("AI 安全最重要的问题是什么？", strategy="debate", rounds=2)
print(result["final"])        # 裁判的最终结论
print(result["rounds"])       # 完整过程记录

# 或从配置文件构建
from deepseek_multi_agent_plugin import build_coordinator
coord = build_coordinator(path="example_config.yaml")
```

## HTTP 适配服务 / HTTP adapter

```bash
python -m deepseek_multi_agent_plugin.adapter_server --port 8000 --demo
# 或：deepseek-plugin-runner --port 8000 --demo
```

```bash
curl -s localhost:8000/health
# {"status": "ok"}

curl -s -X POST localhost:8000/run -H "Content-Type: application/json" -d \
  '{"type": "run", "prompt": "你好", "strategy": "debate", "rounds": 1}'

curl -s localhost:8000/agents
curl -s -X POST localhost:8000/register -H "Content-Type: application/json" -d \
  '{"type": "register", "agents": [{"name": "w1", "kind": "echo"}]}'
```

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/health` | GET | 健康检查 |
| `/agents` | GET | 列出已注册 Agent |
| `/run` | POST | 执行一次协作任务（`{"type":"run","prompt":"...","strategy":"...","rounds":N}`） |
| `/register` | POST | 动态注册 Agent |

## 与 DeepSeek Harness 集成 / Integration with the DeepSeek Harness

`DeepseekAdapter.handle_harness_event(event)` 把外部事件翻译成协调器调用：

```python
from deepseek_multi_agent_plugin import AgentCoordinator, DeepseekAdapter, build_coordinator

coord = build_coordinator(path="example_config.yaml")
adapter = DeepseekAdapter(coord)
result = adapter.handle_harness_event({
    "type": "run",
    "prompt": "设计一个插件架构",
    "strategy": "supervisor",
    "rounds": 3,
})
```

支持的事件类型：`run`、`agents`、`status`、`register`。HTTP 适配服务即基于此接口实现，
因此任何能发起 HTTP 请求的系统（包括 DeepSeek Harness 的工作流）都可以直接调用本插件。

## 开发与测试 / Development

```bash
pip install -e .[dev]
pytest -q
```

GitHub Actions CI 会在 Python 3.10 / 3.11 / 3.12 上运行全部测试。

## License

MIT License. See [LICENSE](LICENSE).
