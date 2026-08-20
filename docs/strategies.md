# 协作策略详解（Collaboration Strategies）

本文档详解 6 种内置协作策略的流程、参数、返回结构与选型建议。所有策略共享统一的结果结构，
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

1. **plan**：主管 Agent 把任务分解为结构化任务计划（JSON 优先，约定
   `{"tasks": [{"id", "description", "agent", "depends_on"}]}`；一行一个任务的纯文本也接受）；
2. **work**：任务交给 DAG 调度器执行——无依赖的任务并行跑，有依赖的任务等依赖完成；
   计划中的 `agent` 指名执行者，未指名时按 agent 的 `capabilities` 匹配路由；
3. **report**：主管看到所有任务结果后，写出最终完整报告。

计划损坏（JSON 解析失败、环依赖、未知依赖、重复 id、未知 agent）会被自动
恢复为保守的可行计划并在 `plan_info` 中记录原因，不会让整个 run 失败。
运行级 deadline 或预算耗尽时，未开始的任务标记 `CANCELLED`，已完成的结果保留。

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
  { "step": "plan", "agent": "supervisor", "response": "{\"tasks\": [...]}" },
  {
    "step": "work",
    "subtasks": ["收集资料", "风险分析"],
    "assigned": { "researcher": ["收集资料"], "critic": ["风险分析"] },
    "results": { "researcher": "结果1", "critic": "结果2" },
    "tasks": [
      { "task_id": "task_1", "status": "SUCCESS", "agent": "researcher", "output": "结果1", "duration_ms": 1200.0 },
      { "task_id": "task_2", "status": "SUCCESS", "agent": "critic", "output": "结果2", "duration_ms": 800.0 }
    ],
    "plan_info": { "format": "json", "notes": [] }
  },
  { "step": "report", "agent": "supervisor", "response": "最终报告" }
]
```

任务状态枚举：`PENDING` / `RUNNING` / `SUCCESS` / `FAILED` / `TIMEOUT` /
`CANCELLED` / `SKIPPED`。菱形依赖（`A → B`、`A → C`、`B,C → D`）会被正确调度。

### 能力路由

agent 配置了 `capabilities`（如 `research,analysis`）而计划中的任务未指名 agent 时，
调度器按任务描述匹配能力标签选择执行者，而非简单轮转分配。

### 适用场景

- 复杂任务天然可拆解（报告、方案、调研），子任务之间有依赖或可并行；
- 希望主管控制分工、最终对产出负责的层级结构。

> 注意：除主管外至少需要 1 个工人，否则抛 `StrategyError`。

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

## 6. relay — 接力迭代（pass-the-baton draft refinement）

### 流程

1. 初始草稿 = 任务提示词本身；
2. 按注册顺序（或 `order` 指定顺序）依次调用每个 Agent，传入「原始任务 + 当前草稿 + 改进要求」，
   每个 Agent 只输出改进后的完整草稿，其输出立即成为新草稿；
3. 所有 Agent 跑完一遍算一轮；每轮结束时对比轮初与轮末草稿：
   - 完全相同 → 已收敛，立即提前结束，`converged = true`；
   - 否则继续下一轮，直到完成 `rounds` 轮或收敛。

### 参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `rounds` | 2 | 最大接力轮数 |
| `order` | 注册顺序 | Agent 接力顺序（Agent 名列表）；名字必须是已注册的 Agent |
| `timeout` | 协调器默认 | 单步超时（秒） |

### 示例

```bash
deepseek-multi-agent run --agents 初稿员,润色员,审校员 --strategy relay \
  --rounds 2 --prompt "写一段产品介绍"
```

```python
result = coord.run("写一段产品介绍", strategy="relay", rounds=3,
                   order=["drafter", "polisher", "reviewer"])
print(result["rounds"][-1]["converged"])   # 该轮是否收敛
for step in result["rounds"][0]["steps"]:
    print(step["agent"], step["response"][:40])
```

### 过程记录结构

```json
[
  {
    "round": 1,
    "kind": "relay",
    "steps": [
      { "step": 1, "agent": "drafter",   "response": "完整草稿v1" },
      { "step": 2, "agent": "polisher",  "response": "完整草稿v2" },
      { "step": 3, "agent": "reviewer",  "response": "完整草稿v3" }
    ],
    "converged": false
  },
  {
    "round": 2,
    "kind": "relay",
    "steps": [
      { "step": 1, "agent": "drafter",   "response": "完整草稿v3" },
      { "step": 2, "agent": "polisher",  "response": "完整草稿v3" },
      { "step": 3, "agent": "reviewer",  "response": "完整草稿v3" }
    ],
    "converged": true
  }
]
```

### 适用场景

- 同一份文案/代码/方案需要多角色依次打磨的创作场景（初稿 → 润色 → 审校 → 定稿）；
- 希望每一步都在上一位的基础上做增量完善，而不是独立产出；
- 希望多轮迭代直到稳定（草稿不再变化就自动停，省 token）。

> 注意：至少需要 2 个 Agent，否则抛 `ValueError`；单轮内某 Agent 抛异常会被跳过，草稿保持不变并记录错误。

---

## 7. auto 策略选择

`strategy="auto"`（默认）按以下规则自动选择：

1. 只有 1 个 Agent → `broadcast`；
2. 存在名为 `supervisor` 的 Agent → `supervisor`；
3. 否则（2 个及以上 Agent）→ `debate`。

想稳定复现某个流程时，建议显式指定策略。

---

## 8. 选型速查

| 你的需求 | 推荐策略 |
| --- | --- |
| 收集多个独立观点，不需要收敛 | broadcast |
| 任务有先后依赖的加工链 | sequential |
| 正反对抗后要一个结论 | debate |
| 大任务拆解 + 并行干活 + 汇总报告 | supervisor |
| 多方案投票定胜负 | consensus |
| 多角色接力打磨同一份草稿，改动即收敛 | relay |
| 不确定选哪个 | auto |
