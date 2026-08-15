# 协作策略详解（Collaboration Strategies）

本文详解 5 种内置协作策略的流程、参数、返回结构与选型建议。所有策略共享统一的结果结构，
并都会把讨论过程写入协调器的共享记忆（`coord.memory`）。

> 上一级：[详细使用说明](usage.md)

---

## 0. 统一结果结构

每种策略都返回一个 dict：

```json
{
  "strategy": "debate",
  "prompt": "原始任务提示词",
  "rounds": [   // 过程记录，策略不同内容不同
    { "round": 1, "kind": "debate", "responses": { "agent_a": "观点", "agent_b": "观点" } }
  ],
  "final": "最终答案",
  "meta": {
    "elapsed_seconds": 1.234,
    "agents": ["agent_a", "agent_b"],
    "strategy": "debate"
  }
}
```

出错约定：某个 Agent 抛异常时其响应为 `{"error": "异常信息"}`；并行阶段超时未返回时为
`{"error": "timeout"}`。出错不影响其他 Agent，也不中断整个任务。

---

## 1. broadcast — 广播讨论

### 流程

1. 所有 Agent 并行收到同一个消息并回答；
2. `rounds > 1` 时，把上一轮所有回答拼接作为下一轮输入，再次并行广播；
3. 最后一轮的回答拼接即为 `final`。

### 参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `rounds` | 1 | 广播轮数 |
| `timeout` | 协调器默认 | 每轮并行阶段超时（秒） |

### 示例

```python
result = coord.run("为一个新产品想 5 个卖点", strategy="broadcast", rounds=2)
```

### 适用场景

- 头脑风暴、多视角平行收集；
- 单 Agent 场景（`auto` 策略在只有 1 个 Agent 时也选它）；
- 需要把多路回答直接合并、不需要收敛的场景。

---

## 2. sequential — 顺序流水线（chain-of-agents）

### 流程

1. 按注册顺序（或 `order` 指定的顺序）逐个调用 Agent；
2. 每个 Agent 看到「原始提示词 + 之前所有 Agent 的发言」完整流水；
3. 最后一个 Agent 的回答即为 `final`。

### 参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `order` | 注册顺序 | 发言顺序（Agent 名列表）；名字必须是已注册的 Agent |
| `timeout` | 协调器默认 | 单步超时（秒） |

### 示例

```bash
deepseek-multi-agent run --demo --strategy sequential \
  --order critic,researcher --prompt "评审这份方案"
```

```python
result = coord.run("写代码并评审", strategy="sequential", order=["coder", "reviewer"])
```

### 适用场景

- 有明显先后依赖的流水线：分析 → 设计 → 实现 → 评审；
- 希望后面的 Agent 完整看到前面工作、做增量加工的链式任务。

> 注意：`order` 里出现未注册的 Agent 名会直接抛 `ValueError`。

---

## 3. debate — 多轮辩论 + 裁判

### 流程

1. 所有 Agent 对同一议题并行发表观点（每轮都携带完整辩论历史）；
2. 重复 `rounds` 轮；
3. 裁判 Agent（`judge`，默认取名为 `judge` 的 Agent，否则取第一个 Agent）综合最后一轮
   所有观点，输出最终结论。

### 参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `rounds` | 3 | 辩论轮数 |
| `judge` | 名为 `judge` 的 Agent，否则第一个 Agent | 裁判 Agent 名 |
| `timeout` | 协调器默认 | 每轮并行阶段超时（秒） |

### 示例

```bash
deepseek-multi-agent run --config example_config.yaml --strategy debate \
  --rounds 3 --judge judge --prompt "AI 安全最重要的问题是什么？"
```

```python
result = coord.run("该不该上微服务？", strategy="debate", rounds=2, judge="judge")
print(result["rounds"][-1])   # 裁判记录：{"step": "judge", "agent": ..., "response": ...}
```

### 适用场景

- 需要正反观点对抗、再收敛出结论的决策（技术选型、方案评审、伦理问题）；
- 团队里有一个明确的中立裁判角色。

> 注意：至少需要 2 个 Agent，否则抛 `ValueError`。

---

## 4. supervisor — 主管-下属

### 流程

1. **plan**：主管 Agent 把任务分解为子任务（约定每行一个）；
2. **work**：子任务按轮转分配给工人 Agent，全部并行执行；
3. **report**：主管看到所有工人结果后，写出最终完整报告。

### 参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `supervisor` | 名为 `supervisor` 的 Agent，否则第一个 Agent | 主管 Agent 名 |
| `workers` | 除主管外的所有 Agent | 工人 Agent 名列表 |
| `timeout` | 协调器默认 | 各阶段超时（秒） |

### 示例

```bash
deepseek-multi-agent run --config example_config.yaml --strategy supervisor \
  --prompt "为校园社团设计一个招新方案"
```

```python
result = coord.run("写一份竞品分析报告", strategy="supervisor",
                   supervisor="manager", workers=["analyst_a", "analyst_b"])
for rec in result["rounds"]:
    print(rec["step"])        # plan / work / report
```

### 过程记录结构

```json
[
  { "step": "plan", "agent": "supervisor", "response": "子任务1\n子任务2" },
  {
    "step": "work",
    "subtasks": ["子任务1", "子任务2"],
    "assigned": { "w1": ["子任务1"], "w2": ["子任务2"] },
    "results": { "w1": "结果1", "w2": "结果2" }
  },
  { "step": "report", "agent": "supervisor", "response": "最终报告" }
]
```

### 适用场景

- 复杂任务天然可拆解（报告、方案、调研）；
- 希望主管控制分工、最终对产出负责的层级结构。

> 注意：除主管外至少需要 1 个工人，否则抛 `ValueError`。

---

## 5. consensus — 提案 + 投票

### 流程

1. **propose**：所有 Agent 并行给出自己的方案；
2. **vote**：所有 Agent 对方案投票，投票文本按 `vote:<agent_name>` 解析（宽松匹配）；
3. **final**：多数票胜出；若平票或无有效票，则由裁判（`judge`，默认名为 `judge` 的 Agent，
   否则第一个 Agent）直接裁决出最终答案。

### 参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `judge` | 名为 `judge` 的 Agent，否则第一个 Agent | 平票时的裁判 |
| `timeout` | 协调器默认 | 各阶段并行超时（秒） |

### 示例

```bash
deepseek-multi-agent run --agents 产品,研发,运营 --strategy consensus \
  --prompt "Q3 优先做哪个功能？"
```

```python
result = coord.run("选数据库", strategy="consensus", judge="cto")
print(result["rounds"][1]["votes"])   # 投票统计，如 {"agent_a": 2, "agent_b": 1}
print(result["rounds"][2]["winner"])  # 胜出者（或走裁判时无此字段）
```

### 投票解析规则

对每个 Agent 的投票文本（小写化后）依次尝试：

1. 与某个 Agent 名完全相等（如 `agent_a`）；
2. 等于 `vote:agent_a` 或 `vote: agent_a`；
3. 文本中包含 `vote:agent_a` 或 `vote: agent_a` 子串。

都不匹配则该票无效。给 LLM 的投票提示词会明确要求输出 `vote:<agent_name>` 格式。

### 适用场景

- 选择题式的集体决策，希望以多数共识收尾；
- 有多个并列候选方案、需要公平比较的场景。

> 注意：至少需要 2 个 Agent，否则抛 `ValueError`。

---

## 6. auto 策略选择

`strategy="auto"`（默认）按以下规则自动选择：

1. 只有 1 个 Agent → `broadcast`；
2. 存在名为 `supervisor` 的 Agent → `supervisor`；
3. 否则（2 个及以上 Agent）→ `debate`。

想稳定复现某个流程时，建议显式指定策略。

---

## 7. 选型速查

| 你的需求 | 推荐策略 |
| --- | --- |
| 收集多个独立观点，不需要收敛 | broadcast |
| 任务有先后依赖的加工链 | sequential |
| 正反对抗后要一个结论 | debate |
| 大任务拆解 + 并行干活 + 汇总报告 | supervisor |
| 多方案投票定胜负 | consensus |
| 不确定选哪个 | auto |
