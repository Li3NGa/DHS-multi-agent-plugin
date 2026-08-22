# Native Runtime API Freeze（packages/dsh-multi-agent）

本文件是已验证 Native Runtime 的 **API 冻结文档**（Phase C）。语义以
`packages/dsh-multi-agent/src` 为准，本文与其不一致时以代码 + 契约测试
（`tests/unit/api-contract.test.ts`）为准，并视为破坏性变更需走版本化。

冻结范围 = 下列 Public API 的**签名与语义**。算法实现不在冻结范围内
（允许修 bug，不允许改语义）。

---

## 0. 分层与 Supervisor 架构约束（强制）

```
Strategy 层（sequential / relay / broadcast / 未来 supervisor）
        │  只允许依赖
        ▼
Task · TaskGraph · Scheduler · AgentRunner(TaskExecute) · Strategy 互相组合
        │
        │  唯一的 DSH 边界（dsh.ts / runner.ts 内部）
        ▼
DSH integration 层：ctx.agents / followup() / whenIdle() / cancel()
                    / session.events（Runtime 内部，不对 Strategy 暴露）
```

**Supervisor（未来）只允许依赖：Task、TaskGraph、Scheduler、AgentRunner
（经 TaskExecute）、既有 Strategy 模式。**

Supervisor 禁止直接接触：DSH Session、DSH 事件流（session.events /
session/event）、DSH Agent 生命周期（create/dispose）、Provider、LLM
adapter。这些属于 Runtime / DSH integration 层，唯一入口是
`AgentRunner.run(task, signal)`。

---

## 1. Public API（包入口 `src/index.ts`）

值导出（11）：`AgentRunner`、`Scheduler`、`Task`、`TaskGraph`、`GraphError`、
`runSequential`、`runRelay`、`runBroadcast`、`apply`、`inject`、
`DEFAULT_TIMEOUT_MS`（常量 `60_000`）。
类型导出（21）：`AgentRunnerOptions, TaskExecute, TaskOutcome,
TaskRawEvents, TaskSpec, TaskStatus, TaskMetadata, SchedulerOptions,
SchedulerReport, SequentialOptions, SequentialReport, SequentialStep,
RelayOptions, RelayReport, BroadcastOptions, BroadcastReport, DshContext,
DshAgentHandle, DshAgentLookup, SessionEvent, UserMessage` 及
`PluginConfig, MultiAgentApi`。

插件装配（宿主侧）：`apply(ctx, config?)` 经 `ctx.reflect.provide(
'multiAgent', api)` 注册 `ctx.multiAgent`（随 fiber 卸载）；
`inject = ['agents']`。`PluginConfig.concurrency` 为默认并发，
`defaultTimeoutMs` 缺省取 `DEFAULT_TIMEOUT_MS`。

## 2. Internal API（不承诺稳定）

- `dsh.ts`：`DshAgentHandle / DshAgentLookup / DshContext / lookupAgent`
  ——DSH 端口，宿主类型变化时的唯一调整点（随真实 DSH 类型校正）。
- `runner.ts`：`outcomeFromEvents(taskId, events, inputs)`（导出供测试）、
  `errorMessage`、`extractText`、`makeUserMessage`。
- `scheduler.ts`：私有调度循环、`_Running` 等价内部态。
- `graph.ts`：`#findCycle` / `#depsCompleted` 等私有方法。
- 策略内部：`relayMessage`、各策略的 prompt/draft 传递闭包。

## 3. Task API

```ts
type TaskStatus = 'pending' | 'ready' | 'running' | 'completed' | 'failed' | 'cancelled'
interface TaskSpec { id; agentId; prompt; dependsOn?; timeoutMs?; metadata? }
class Task {
  readonly id: string; readonly agentId: string; readonly prompt: string
  readonly dependsOn: readonly string[]; readonly timeoutMs: number | undefined
  readonly metadata: TaskMetadata            // 冻结快照（浅冻结）
  status: TaskStatus                          // 初始 'pending'
  get isTerminal(): boolean                   // completed|failed|cancelled
  withPrompt(prompt: string): Task            // 保 id/依赖/选项的副本
}
function isTerminalStatus(status): boolean
```

构造校验（TypeError）：`id`/`agentId` 非空字符串；`prompt` 为 string；
`timeoutMs` 为有限数 > 0；`dependsOn` 内不重复。
状态迁移由 TaskGraph/Scheduler 驱动；`Task` 不接触 LLM/Session/Provider。

## 4. TaskGraph API

```ts
class TaskGraph {
  add(spec: TaskSpec | Task): Task            // 重复 id → GraphError('duplicate-id')
  get(id): Task | undefined
  has(id): boolean
  get size(): number
  tasks(): readonly Task[]                    // 插入序
  dependencies(id): readonly string[]         // 声明序；未知 id → GraphError('unknown-task')
  dependents(id): readonly string[]           // 插入序；未知 id → GraphError('unknown-task')
  ready(): readonly Task[]                    // 纯查询：pending 且依赖全 completed，插入序
  isComplete(): boolean                       // 全部任务终态
  validate(): void                            // 见下
}
class GraphError extends Error { code: GraphErrorCode }
type GraphErrorCode = 'duplicate-id' | 'unknown-task' | 'missing-dependency'
                    | 'self-dependency' | 'cycle'
```

`validate()` 严格拒绝（**从不静默修复**）：missing dependency、self
dependency、cycle（报错含环路径 `a -> b -> a`）。Scheduler 在执行前必须
`validate()`。`ready()` 不改变状态、不消费任务。

## 5. Scheduler API

```ts
type TaskExecute = (task: Task, signal: AbortSignal) => Promise<TaskOutcome>
interface SchedulerOptions { concurrency?: number }   // 整数 ≥ 1，缺省不限
interface SchedulerReport {
  results: ReadonlyMap<string, TaskOutcome>  // 按图插入序（确定性）
  order: readonly string[]                   // 实际完成序
  ok: boolean                                // 全部 completed
  stopped: boolean                           // 因 stop()/AbortSignal 终止
}
class Scheduler {
  constructor(execute: TaskExecute, options?)
  run(graph: TaskGraph, signal?: AbortSignal): Promise<SchedulerReport>
  stop(): void                               // 协作终止当前 run
}
```

语义（冻结）：
- **依赖序**：依赖全部 `completed` 才启动；`failed`/`cancelled` 依赖 →
  依赖者记 `cancelled`，error 为 `dependency '<id>' <status>`。
- **并发**：in-flight ≤ `concurrency`；启动顺序 = 插入序。
- **确定性结果序**：`results` Map 迭代序恒为插入序（与完成序无关）。
- **取消**：外部 signal 中止或 `stop()` → pending/in-flight 全部
  `cancelled`；在途 promise 迟到结果被丢弃；`run()` 正常 resolve（带
  `stopped: true`），不抛异常。
- **终止**：全部任务终态即返回；每个任务必有 TaskOutcome。
- execute 抛异常 → 该任务 `failed`（error=消息），不中止整个 run。
- 同一 Scheduler 实例并发第二次 `run()` → 抛错；非法图 → `validate()`
  抛 `GraphError`；`concurrency` 非法 → TypeError。
- 事件驱动，无 sleep / 随机延迟。

## 6. AgentRunner API

```ts
class AgentRunner {
  constructor(ctx: DshContext, options?: { defaultTimeoutMs?: number })
  run(task: Task, signal?: AbortSignal): Promise<TaskOutcome>
}
```

流程（冻结）：查 `ctx.agents`（缺失 → `failed("agent '<id>' not found")`）
→ 记 `session.events` 基线 → `followup(UserMessage)`（void）→
`whenIdle()` 与 timeout/signal 竞速 → **按基线切片**推导结果。

## 7. Result model

```ts
type TaskOutcomeStatus = 'completed' | 'failed' | 'cancelled'
interface TaskOutcome {
  taskId: string; status; text?: string; error?: string
  durationMs: number
  raw?: TaskRawEvents   // { assistantMessages, toolCalls, toolResults, turnEndReason }
}
```

文本 = 切片内 `assistant/message` 的 text 块（跳过 usage-only 空消息），
多步以 `\n\n` 连接；`interrupted: true` 前缀保留为取消/超时任务的
partial text。策略层报告：`SequentialReport{steps, final, ok}`、
`RelayReport{draft, turns, ok}`、`BroadcastReport{responses, joined, ok}`。

## 8. Error model

- `GraphError`（结构错误，五种 code，见 §4）——执行前抛出。
- `TaskOutcome.error`（执行期）：agent 缺失、timeout、turn/end 错误语义
  （error/blocked/max-tells）、execute 异常、依赖级联原因。
- `TypeError`（构造/参数校验）。
- 策略/调度层**不因任务失败而抛异常**；run 级异常仅限：非法图、并发
  run、调度器内部不变量破坏。

## 9. Timeout semantics（冻结）

- 任务上限 = `task.timeoutMs ?? runner defaultTimeoutMs`（插件装配缺省
  `DEFAULT_TIMEOUT_MS = 60s`）→ 任何任务都有上限，run 不可能永久悬挂。
- 到期路径：`agent.cancel({ kind: 'hook', reason })`（宿主机制）→
  `whenIdle()` 收敛 → 结果 `failed`，error 前缀 `timeout:`，保留
  interrupted 前缀文本。
- 宿主能力边界：cancel 后 harness 若仍不收敛，有界 grace
  `max(5s, 2×timeout)` 按日志现状结算——不 sleep 轮询、不强杀。

## 10. Cancellation semantics（冻结）

- 取消总是协作式：外部 `AbortSignal`（run 前/中）或 `Scheduler.stop()`。
- 取消前已完成的任务保留真实结果；未启动/在途 → `cancelled`；迟到
  结果丢弃；`report.stopped = true`。
- AgentRunner 在 signal 已中止时直接返回 `cancelled`（不发起 followup）；
  在途中止 → `agent.cancel(hook)` → `cancelled`。

## 11. Lifecycle semantics（冻结）

- Task：`pending → ready → running → 终态(completed|failed|cancelled)`；
  终态不可逆；每个进入 run 的任务必有终态 + TaskOutcome。
- Scheduler.run：单飞行；结束即释放（可复用实例再次 run）。
- 插件：cordis fiber 装载 `apply` → `ctx.multiAgent` 提供；fiber dispose
  → 服务卸载（冒烟已验证无残留、可重载）。

## 12. Extension points（未来 Supervisor 的合法接入面）

1. **新 Strategy**：`runXxx(execute: TaskExecute, ...)` 纯函数模式，
   组合 TaskGraph + Scheduler（参照 sequential/relay/broadcast）。
2. **TaskExecute 装饰**：包装默认 execute（如注入计划上下文 prompt），
   不触碰 DSH 层。
3. **SchedulerOptions.concurrency**：per-run 并发策略。
4. **Task.metadata**：自由只读载荷（策略间传递计划信息）。
5. 非法扩展面（禁止）：绕过 AgentRunner 直接 followup、读取
   session.events、自建 Agent/Session/LLM/线程池。

---

维护规则：本文档 + `tests/unit/api-contract.test.ts` 共同构成冻结。
对 Public API 的任何增删改（含默认值）= 破坏性变更，需升 minor/major
并在此记录。

## 13. Strategy Contract（Phase D 冻结增补）

三种策略（Broadcast / Sequential / Relay）的报告统一实现公共信封
`StrategyReport`（`src/strategies/contract.ts`）：

```ts
interface StrategyReport {
  strategy: 'broadcast' | 'sequential' | 'relay'
  status: 'success' | 'partial' | 'failed' | 'cancelled'
  ok: boolean                    // === status 'success'
  stopped: boolean               // 经 stop()/AbortSignal 终止（Scheduler 语义）
  tasks: readonly StrategyTask[] // 每 task 一项，声明序；correlation = taskId
  outputs: readonly string[]     // completed 文本，声明序
  errors: readonly { taskId; error }[]
  metadata: { taskCount; completed; failed; cancelled; timedOut }
}
```

- `tasks[].status` 复用 TaskOutcomeStatus（无第二套结果模型）；策略专属
  字段（steps/turns/responses/final/draft/joined）作为扩展保留，差异
  只存在于策略内部——未来 Supervisor 只依赖本信封。
- run 级 status 推导（冻结）：`stopped → 'cancelled'`；否则全 completed
  → `'success'`；有 completed → `'partial'`；否则 `'failed'`。空输入为
  `'success'`（与既有空报告 `ok: true` 行为一致）。
- **错误分层**：TaskError = `tasks[].error`（agent 缺失 / timeout 前缀 /
  依赖级联 `dependency 'x' ...` / execute 异常），永不吞掉；StrategyError
  = 无新增异常类型——任务失败不抛出，中止即 `status 'cancelled' +
  stopped`；RuntimeError = GraphError / TypeError（结构/参数错误）原样
  传播。
- **timeout / cancellation**：策略不自建任何定时器或取消机制，全部经
  §5/§9/§10 的 Runtime 语义（signal 透传 Scheduler；timeout 由
  AgentRunner 结算为 `failed` + `timeout:` 前缀错误）。
