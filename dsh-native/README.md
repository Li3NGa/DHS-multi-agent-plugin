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

## 已知边界

- **DSH 端口未对实物验证**：`src/dsh.ts` 按 `ctx.agents` / `followup()` /
  `whenIdle()` / 事件列表建模；拿到真实 DSH 类型定义后只需校正该文件与
  `runner.ts` 的 `normalizeReply`。
- 超时与取消是协作式的：JS promise 无法杀死，任务立刻结算为
  failed/cancelled，底层调用继续浮动至自行结束（与 Python 基线一致）。
- Relay 中途失败会取消后续步骤（调度器失败传播语义）；Python relay
  失败后继续传递旧草稿——这是记录在案的实现差异。
