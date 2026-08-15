# 详细使用说明（Usage Guide）

本指南介绍如何完整使用 `deepseek-multi-agent-plugin`：从安装、配置 Agent 团队，到用命令行 /
Python API / HTTP 服务三种方式运行多智能体协作任务，再到接入真实 LLM（DeepSeek、OpenAI 或
任意兼容端点）。

> 相关文档：
> - [协作策略详解](strategies.md) — 6 种策略的流程、参数与选型
> - [Python API 参考](api_reference.md) — 全部类与函数的签名说明
> - [HTTP 服务接口](http_api.md) — 四个端点的请求/响应协议

---

## 1. 安装与准备

要求：Python >= 3.9（3.10–3.12 经过 CI 验证）。

```bash
pip install deepseek-multi-agent-plugin
```

核心功能零运行时依赖（LLM 调用走标准库 urllib）。可选依赖：

| 依赖 | 用途 | 安装方式 |
| --- | --- | --- |
| PyYAML | 加载 `.yaml` / `.yml` 配置文件 | `pip install pyyaml` |
| pytest | 运行测试 | `pip install pytest` |

```bash
# 开发安装（含全部可选依赖）：
pip install -e ".[dev]"
```

如果要调用真实 LLM，先准备 API Key（见第 8 节）。

---

## 2. 快速开始（30 秒上手）

不需要任何 API Key，用两个内置演示 Agent 跑一场辩论：

```bash
deepseek-multi-agent run --demo --strategy debate --rounds 2 \
  --prompt "AI 安全当前最重要的问题是什么？"
```

输出会依次展示：每轮各 Agent 的观点、裁判的最终结论。加 `--json` 可输出完整结构化结果：

```bash
deepseek-multi-agent run --demo --strategy consensus --json --prompt "帮我选个技术栈"
```

`--demo` 注册了两个 mock Agent（`researcher`、`critic`），适合先跑通流程、理解策略行为。

---

## 3. 配置 Agent 团队

团队配置可以写在一个 YAML 或 JSON 文件里，命令行、Python API、HTTP 服务都能复用。

### 3.1 YAML 示例

```yaml
coordinator:
  strategy: debate      # 默认策略（可选，运行时也可覆盖）
  rounds: 3             # 默认轮数
  timeout_seconds: 30   # 每阶段超时

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

### 3.2 Agent 字段说明

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `name` | 是 | 唯一标识，出现在所有记录与内存中 |
| `kind` | 否 | `mock` / `echo` / `http` / `deepseek` / `openai` / `custom` / `cli`；省略时若提供 `handler` 则视为 `custom`，否则为 `mock` |
| `role` | 否 | 角色描述（自由文本，仅作元信息） |
| `system_prompt` | 否 | 系统提示词，每次 LLM 调用都会前置 |
| `model` | 否 | 模型名，如 `deepseek-chat`、`deepseek-reasoner`、`gpt-4o-mini` |
| `temperature` | 否 | 采样温度 0–2 |
| `max_tokens` | 否 | 最大生成 token 数 |
| `api_key` | 否 | 显式 API Key；缺省读环境变量（见第 8 节） |
| `base_url` | 否 | 覆盖默认 API 地址（可指向任何 OpenAI 兼容端点） |
| `timeout` | 否 | 单次 LLM 调用超时（秒，默认 60）；cli agent 的子进程超时（秒，默认 300） |
| `message_template` | mock 用 | 模板字符串，支持 `{msg}` 与 `{name}` 占位符 |
| `url` | http 用 | 接收 `{"message": ...}` JSON 的端点地址 |
| `handler` | custom 用 | Python 可调用对象（仅代码中可用，YAML 无法序列化） |
| `command` | cli 用 | 可执行文件路径或 PATH 中的命令名（必填） |
| `args` | cli 用 | 传给命令的参数列表（默认 `[]`，不含消息本身） |
| `cwd` | cli 用 | 子进程工作目录（可选） |
| `encoding` | cli 用 | stdout/stderr 解码编码（默认 `utf-8`） |

### 3.3 运行配置

`coordinator` 段只提供默认值，运行时（CLI 参数 / HTTP 请求字段 / `run()` 关键字）可以覆盖：

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `strategy` | `auto` | 协作策略，见 [strategies.md](strategies.md) |
| `rounds` | 3 | 轮数（broadcast/debate 使用） |
| `timeout_seconds` | 15 | 每个并行阶段的总超时（秒） |

---

## 4. 六种协作策略速览

| 策略 | 中文名 | 一句话说明 | 适用场景 |
| --- | --- | --- | --- |
| `broadcast` | 广播讨论 | 所有 Agent 并行回答，`rounds>1` 时把上轮汇总回喂 | 头脑风暴、平行观点收集 |
| `sequential` | 顺序流水线 | 按指定顺序逐个发言，每人看到完整历史 | 分析→设计→实现→评审的流水线 |
| `debate` | 多轮辩论 | 先辩 N 轮，再由裁判综合出最终结论 | 需要对抗与收敛的决策 |
| `supervisor` | 主管-下属 | 主管分解子任务，工人并行执行，主管汇总报告 | 复杂任务拆解与并行执行 |
| `consensus` | 提案-投票 | 每人提案，全员投票多数胜出，平票由裁判裁决 | 需要多数共识的选择题 |
| `relay` | 接力迭代 | 按顺序轮流打磨同一份草稿，无改进即提前收敛 | 初稿→润色→审校的文稿打磨 |

策略的完整流程、参数与示例输出见 [协作策略详解](strategies.md)。

---

## 5. 命令行工具

### 5.1 `run` — 运行协作任务

```bash
deepseek-multi-agent run --prompt "任务描述" [选项]
```

| 选项 | 说明 |
| --- | --- |
| `--prompt` | 任务提示词（必填） |
| `--strategy` | `auto`（默认）/ `broadcast` / `sequential` / `debate` / `supervisor` / `consensus` / `relay` |
| `--rounds` | 轮数，默认 3 |
| `--judge` | 裁判 Agent 名（debate/consensus） |
| `--order` | 逗号分隔的发言顺序（sequential），如 `--order critic,researcher` |
| `--timeout` | 每阶段超时秒数 |
| `--config` | YAML/JSON 配置文件 |
| `--demo` | 使用两个内置 mock Agent |
| `--agents` | 逗号分隔的 mock Agent 名，如 `--agents a,b,c` |
| `--json` | 输出完整 JSON（含每轮记录与元信息） |

示例：

```bash
# 用配置文件里的 DeepSeek 团队跑主管模式
deepseek-multi-agent run --config example_config.yaml --strategy supervisor \
  --prompt "为校园社团设计一个招新方案" --json

# 指定流水线顺序
deepseek-multi-agent run --demo --strategy sequential --order critic,researcher \
  --prompt "评审这个方案"

# 三个 mock Agent 跑共识
deepseek-multi-agent run --agents 产品,研发,运营 --strategy consensus --prompt "Q3 做什么功能？"
```

### 5.2 `agents` — 查看团队

```bash
deepseek-multi-agent agents --config example_config.yaml
# {"name": "researcher", "role": "研究员", "provider": "deepseek", "model": "deepseek-chat", ...}
```

### 5.3 `serve` — 启动 HTTP 服务

```bash
deepseek-multi-agent serve --config example_config.yaml --port 8000
deepseek-plugin-runner --port 8000 --demo        # 等价的旧命令名
```

接口协议见 [HTTP 服务接口](http_api.md)。

---

## 6. Python API

### 6.1 最小示例

```python
from deepseek_multi_agent_plugin import AgentCoordinator, AgentFactory

coord = AgentCoordinator()
coord.register_agent(AgentFactory.create_agent('mock', 'a', message_template='A说: {msg}'))
coord.register_agent(AgentFactory.create_agent('mock', 'b', message_template='B说: {msg}'))

result = coord.run("今天中午吃什么？", strategy="debate", rounds=1)
print(result["final"])   # 最终结论
print(result["rounds"])  # 完整过程
```

### 6.2 从配置文件构建

```python
from deepseek_multi_agent_plugin import build_coordinator

coord = build_coordinator(path="example_config.yaml")
result = coord.run("设计一个插件架构", strategy="supervisor")
```

### 6.3 共享记忆

每次 `run` 都会把提示词和各 Agent 的发言写入协调器共享的 `MessageStore`：

```python
print(coord.memory.all())          # 全部消息
print(coord.memory.to_chat())      # 转成 OpenAI chat 格式
coord.memory.clear()               # 清空
```

### 6.4 错误与超时

- 某个 Agent 抛异常：该 Agent 的响应记为 `{"error": "..."}`，不影响其他 Agent。
- 并行阶段整体超时：未完成的 Agent 记为 `{"error": "timeout"}`。
- `run()` 会忽略策略不认识的额外关键字参数（如给 broadcast 传 `judge`），方便统一调用。

完整签名与说明见 [Python API 参考](api_reference.md)。

---

## 7. HTTP 服务

```bash
python -m deepseek_multi_agent_plugin.adapter_server --port 8000 --demo
```

```bash
curl -s localhost:8000/health
curl -s localhost:8000/agents
curl -s -X POST localhost:8000/run -H "Content-Type: application/json" -d \
  '{"type": "run", "prompt": "你好", "strategy": "debate", "rounds": 1}'
curl -s -X POST localhost:8000/register -H "Content-Type: application/json" -d \
  '{"type": "register", "agents": [{"name": "w1", "kind": "echo"}]}'
```

协议详见 [HTTP 服务接口](http_api.md)。

---

## 8. 接入真实 LLM

### 8.1 DeepSeek 官方 API

```bash
export DEEPSEEK_API_KEY=sk-xxxxxxxx          # Windows: set DEEPSEEK_API_KEY=sk-xxxxxxxx
```

```yaml
# 配置里写 kind: deepseek 即可，模型默认为 deepseek-chat
agents:
  - name: analyst
    kind: deepseek
    model: deepseek-chat
    system_prompt: 你是一名资深分析师。
```

### 8.2 OpenAI / 任意兼容端点

```bash
export OPENAI_API_KEY=sk-xxxxxxxx
```

```yaml
agents:
  - name: assistant
    kind: openai
    model: gpt-4o-mini
  - name: local_llm
    kind: openai
    base_url: http://localhost:8000/v1
    api_key: dummy,                     # 本地服务通常忽略 key
    model: qwen2.5-72b-instruct
```

> 提示：`kind: deepseek` 与 `kind: openai` 走同一套 OpenAI 兼容协议，区别只是默认地址、
> 默认模型和环境变量名。任何实现 `POST /chat/completions` 的服务都可以通过 `base_url` 接入。

### 8.3 外部 agent CLI 桥接（kind: cli）

任何能读取命令行参数并从 stdout 返回结果的外部程序（codex CLI、任意 CLI 工具）都可以
作为团队一员：handler 会执行 `command + args + [消息]`，按退出码与输出返回内容。

```yaml
agents:
  - name: codex_worker
    kind: cli
    command: C:/Users/admin/AppData/Local/OpenAI/Codex/bin/e305f1c75d8da435/codex.exe
    args: [exec, --skip-git-repo-check]
    timeout: 600
```

- 消息会作为最后一个参数追加，适合 `codex exec "<prompt>"` 这类一次性执行模式；
- 退出码 0 且 stdout 非空时返回 stdout；stdout 为空则返回 stderr；非 0 退出码或超时会
  记录为 `{"error": ...}`，不会中断协作；
- `command` 也可以是 PATH 中的命令名（如 `codex`），`cwd` 可指定工作目录。

### 8.4 代码中直接构造 LLM Agent

```python
from deepseek_multi_agent_plugin import Agent

agent = Agent(
    "coder",
    provider="deepseek",
    system_prompt="你是一名资深 Python 工程师。",
    model="deepseek-chat",
    temperature=0.2,
    api_key="sk-xxx",          # 或省略，读 DEEPSEEK_API_KEY 环境变量
)
```

### 8.5 预算与速率提示

- 辩论 N 轮 × M 个 Agent ≈ M×N 次 LLM 调用，另加 1 次裁判调用；supervisor 为 2 次主管调用 + 工人调用。
- 每轮辩论都会携带历史上下文，轮数过多时注意 token 消耗；`MessageStore` 可设 `capacity` 截断。

---

## 9. 与 DeepSeek Harness 集成

`DeepseekAdapter` 把 JSON 事件翻译成协调器调用，HTTP 服务就是它的一个外壳。任何能发 HTTP
请求的系统（包括 Harness 工作流）都可以直接使用：

```python
from deepseek_multi_agent_plugin import AgentCoordinator, DeepseekAdapter

adapter = DeepseekAdapter(AgentCoordinator())
result = adapter.handle_harness_event({
    "type": "run",
    "prompt": "写一份竞品分析",
    "strategy": "supervisor",
    "rounds": 3,
})
```

支持的事件：`run`（执行任务）、`agents`（列出团队）、`status`（健康状态）、`register`（动态注册）。
事件字段与返回值格式见 [HTTP 服务接口](http_api.md) 中的协议表。

---

## 10. 常见问题（FAQ）

**Q1：提示 `missing API key`？**

deepseek Agent 需要 `DEEPSEEK_API_KEY` 环境变量（或配置里的 `api_key`），openai Agent 需要
`OPENAI_API_KEY`。用 `--demo` 或 mock Agent 则不需要任何 key。

**Q2：YAML 配置报错 `PyYAML is required`？**

```bash
pip install pyyaml
```

或把配置写成 JSON 文件（标准库即可解析）。

**Q3：`debate` / `consensus` 报错 `needs at least two agents`？**

这两个策略需要至少 2 个 Agent；单 Agent 请用 `broadcast`。

**Q4：某个 Agent 一直超时？**

用 `--timeout` / `timeout_seconds` 调大并行阶段超时；单次 LLM 调用超时用 Agent 的 `timeout` 字段。

**Q5：如何清空历史记忆？**

```python
coord.memory.clear()
```

**Q6：HTTP 服务怎么暴露到外网？**

服务本身没有鉴权与 TLS，建议放在内网或反代后（如 Nginx + 基本认证），不要直接暴露公网。

---

## 11. 相关文档

- [协作策略详解](strategies.md)
- [Python API 参考](api_reference.md)
- [HTTP 服务接口](http_api.md)
- [示例代码](../examples/)：`demo_strategies.py`（全策略演示，无需 Key）、`demo_deepseek_team.py`（真实 LLM 团队）、`run_http_server.py`（HTTP 服务）
