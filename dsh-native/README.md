# DSH Native Multi-Agent Orchestration (Phase 2)

DSH 原生的多智能体编排基础运行时（TypeScript / Cordis plugin）。Python 运行时
（`src/deepseek_multi_agent_plugin/`）保留为 reference implementation /
regression baseline；本目录只迁移经过验证的行为，不复制实现细节。

## 结构

```
src/
  task.ts               Task 类型与状态（pending/ready/running/completed/failed/cancelled）
  graph.ts              TaskGraph：严格 DAG（duplicate id / missing dep / self dep / cycle 全部报错）
  dsh.ts                DSH API ports（ctx.agents / followup / whenIdle；接入真实 DSH 类型时在此校正）
  runner.ts             AgentRunner：Task -> ctx.agents，超时/取消/回复归一化
  scheduler.ts          Scheduler：依赖排序、并发上限、失败传播、取消、确定性结果序
  strategies/
    sequential.ts       A -> B -> C（依赖 ≠ 结果传递：prompt builder 显式接收上一步结果）
    relay.ts            草稿接力（RelayContext 显式上下文传递，不改 Session）
    broadcast.ts        并行广播（按声明顺序返回结果）
  index.ts              Cordis 插件入口（apply + inject: ['agents']）
```

## 命令

```bash
npm install
npm run typecheck   # tsc --noEmit（strict + exactOptionalPropertyTypes）
npm test            # vitest run
npm run build       # esbuild -> dist/dsh.bundle.js
```

## 接入 DSH

```yaml
# ~/.dsh/profiles/<profile>/cordis.patch.yml
plugins:
  dsh-multi-agent:
    $path: <repo>/dsh-native/dist/dsh.bundle.js
    concurrency: 8            # 可选：默认不限
    defaultTimeoutMs: 60000   # 可选：单任务默认超时
```

插件挂载后通过 `ctx.multiAgent` 暴露：

```ts
ctx.multiAgent.scheduler({ concurrency: 4 })
ctx.multiAgent.runSequential(steps, { signal })
ctx.multiAgent.runRelay({ prompt, steps })
ctx.multiAgent.runBroadcast({ prompt, agents })
```

## 真实 DSH 验证（smoke）

`npm run test:smoke` 启动**真实 DeepSeek Harness 运行时**（`@deepseek-ai/cordis`
Context + dsh-llm / dsh-session / dsh-system-prompt / dsh-tools / dsh-agent /
dsh-agent-loop，0.1.1-rc.2 线），经真实 `ctx.llm.registerAdapter` 注册脚本化
模型端点（DSH 官方测试同款模式，无需 API key），覆盖：

- A 插件加载（cordis `ctx.plugin`，`inject: ['agents']`）
- B `ctx.multiAgent` 经 `ctx.reflect.provide` 注册
- C `ctx.agents` 解析真实 agent
- D 单任务（真实 turn/session events）
- E 广播（2 agent 并行）
- F Sequential 结果传递
- G Relay 草稿接力
- H 任务超时 → 真实 `turn/end { aborted }`，run 不悬挂
- I AbortSignal 取消 → 真实 turn 中止
- Task1/Task2 隔离：同 agent 顺序两任务，task 2 的结果切片不包含
  task 1 的 assistant message（`session.events` seq 边界 = correlation）
- **发布验证**（`smoke/dsh.bundle.spec.ts`）：真实 runtime 加载**构建产物**
  `dist/dsh.bundle.js`（external 依赖经真实 node_modules 解析）、插件 fiber
  卸载后 `ctx.multiAgent` 无残留、重载可用；**config 声明式 agent**
  （DSH config → agent_loop.create → ctx.agents → 单任务/广播/Sequential/
  Relay）全链路。
- 边界：桌面/TUI 的 cordis.patch.yml 装载路径未在本机验证（无 ~/.dsh
  桌面安装），见 `cordis.patch.yml.example`。

## 设计要点（真实 API 对齐）

- `followup(UserMessage): void` 无返回值；结果一律取自 `agent.session.events`
  （`seq === index` 的 append-only 日志）。任务前记录 baseline、`whenIdle()`
  后切片 —— 这是 task 级 correlation，杜绝读到前一个任务的回复。
- 超时/取消走宿主机制：`agent.cancel({ kind: 'hook', reason })` 中止活跃
  turn，`whenIdle()` 收敛；`interrupted: true` 的 assistant 前缀保留为部分
  文本。无 sleep、无线程强杀。宿主能力边界：若 harness 在 cancel 后仍不
  收敛，退化为有界 grace（max(5s, 2×timeout)）后按日志现状结算。
- `defaultTimeoutMs` 默认 60s（`DEFAULT_TIMEOUT_MS`），任何任务都有超时上限。
- 插件服务经 `ctx.reflect.provide('multiAgent', api)` 暴露，随 fiber 卸载。

## 已知边界

- **真实 LLM 端点未接入**：smoke 使用脚本化 adapter（无 API key 环境）；
  `ctx.agents` / `followup` / `whenIdle` / session events / cancel 已在真实
  harness 上验证（见上）。真实 provider 路径由 DSH 自身保证。
- 超时与取消是协作式的：JS promise 无法杀死，任务立刻结算为
  failed/cancelled，底层调用继续浮动至自行结束（与 Python 基线一致）。
- Relay 中途失败会取消后续步骤（调度器失败传播语义）；Python relay
  失败后继续传递旧草稿——这是记录在案的实现差异。
