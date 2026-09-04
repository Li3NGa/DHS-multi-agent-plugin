<div align="center">

# dsh-multi-agent

[![npm](https://img.shields.io/npm/v/dhs-multi-agent.svg)](https://www.npmjs.com/package/dhs-multi-agent)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](../../LICENSE)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)

**DeepSeek Harness 多智能体编排插件**

[快速开始](#快速开始) ·
[核心特性](#核心特性) ·
[API](#公共-api) ·
[开发](#开发)

</div>

---

## 核心特性

### 🔄 策略执行
- **Sequential** — 顺序串行执行
- **Broadcast** — 广播并行执行
- **Relay** — 接力式传递
- **DAG** — 任意依赖图直接执行

### 🧠 规划与路由
- **Planner** — 从自然语言生成结构化任务
- **Validator** — 严格的计划验证
- **AgentRouter** — 基于能力的智能体路由

### 🛡️ 有界恢复
- **Retry** — 超时失败自动重试
- **Repair** — 不可用智能体自动剔除
- **Replan** — 依赖失败确定性重规划
- **Abort** — 取消不触发恢复

### 📊 可观测性
- `RuntimeDiagnostics` — 诊断指标
- `RunRegistry` — 运行注册追踪
- Observer 模式回调

---

## 快速开始

### 安装

```bash
npm install dhs-multi-agent
```

### 使用

```typescript
import { apply } from 'dhs-multi-agent'

apply(ctx, {
  concurrency: 4,
  defaultTimeoutMs: 60_000,
})

// DAG 执行
const result = await ctx.multiAgent.runDag([
  { id: 'a', agentId: 'agent1', prompt: '任务 A' },
  { id: 'b', agentId: 'agent2', prompt: '任务 B', dependsOn: ['a'] },
])

// 带恢复的编排
const recovered = await ctx.multiAgent.runWithRecovery(plan, {
  runId: 'run-1',
  agents: [
    { id: 'researcher', capabilities: ['research'] },
    { id: 'writer', capabilities: ['writing'] },
  ],
  recovery: { maxAttempts: 3, maxReplans: 2 },
})
```

---

## 公共 API

```typescript
import {
  // 核心
  AgentRunner,
  Scheduler,
  Task,
  TaskGraph,
  // 策略
  runSequential,
  runBroadcast,
  runRelay,
  runDag,
  // Supervisor
  createSupervisor,
  // 恢复
  createRecoveryManager,
  // 诊断
  RuntimeDiagnostics,
  RunRegistry,
  createRuntimeDiagnostics,
  // 插件
  apply,
} from 'dhs-multi-agent'
```

---

## 架构

```text
input
  → Planner
  → Validator
  → Router
  → Supervisor / Direct DAG
  → Strategy / Scheduler
  → AgentRunner
  → Real DSH
  → Recovery / Diagnostics
```

---

## 开发

```bash
# 安装依赖
pnpm install --frozen-lockfile

# 类型检查
pnpm typecheck

# 单元测试
pnpm test

# 构建
pnpm build

# Smoke 测试
pnpm test:smoke
```

---

## DSH 集成

使用根目录的 `cordis.patch.yml` 或本包中的示例配置。
Smoke 测试套件使用发布的 `@deepseek-ai/*` 运行时包和脚本化适配器，无需 API Key。

---

## 许可证

MIT © DHS Multi-Agent Contributors
