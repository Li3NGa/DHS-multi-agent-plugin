# DHS Multi-Agent Orchestration

[![CI](https://github.com/Li3NGa/DHS-multi-agent-plugin/actions/workflows/ci.yml/badge.svg)](https://github.com/Li3NGa/DHS-multi-agent-plugin/actions/workflows/ci.yml)
[![Native Runtime](https://github.com/Li3NGa/DHS-multi-agent-plugin/actions/workflows/native-runtime.yml/badge.svg)](https://github.com/Li3NGa/DHS-multi-agent-plugin/actions/workflows/native-runtime.yml)
[![npm](https://img.shields.io/npm/v/dhs-multi-agent.svg)](https://www.npmjs.com/package/dhs-multi-agent)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

**Native DeepSeek Harness (DSH) multi-agent orchestration for Cordis.**

`dhs-multi-agent` turns a DSH agent runtime into a structured multi-agent execution layer with DAG scheduling, supervisor planning, bounded recovery, and runtime diagnostics.

The production Native source tree is `packages/dsh-multi-agent/src/`. The published root package is the Native distribution. The Python runtime remains available under `src/deepseek_multi_agent_plugin/` as a separate compatibility surface.

## Install

```bash
npm install dhs-multi-agent
```

Requirements:

- Node.js `>=22.14.0`
- A host providing the DeepSeek Harness / Cordis runtime packages used by this plugin

The package externalizes `@deepseek-ai/*` runtime modules in its bundle; the host supplies those modules.

## Native architecture

```text
User intent / task plan
        |
        v
     Planner
        |
        v
    Validator
        |
        v
      Router
        |
        +--------------------+
        |                    |
        v                    v
   Supervisor             Direct DAG
        |                    |
        v                    v
    Strategy             Scheduler
        |                    |
        +---------+----------+
                  |
                  v
             AgentRunner
                  |
                  v
              Real DSH
                  |
                  v
        Recovery / Diagnostics
```

The current Native V1 production path deliberately keeps the verified Supervisor Strategy Contract small:

- `sequential`
- `broadcast`
- `relay`

The runtime also exposes direct DAG execution through `runDag()` / `planAndRunDag()` without changing that frozen Supervisor contract.

## Public API

The package exports the runtime building blocks directly:

```ts
import {
  AgentRunner,
  Scheduler,
  Task,
  TaskGraph,
  runSequential,
  runBroadcast,
  runRelay,
  runDag,
  Supervisor,
  createSupervisor,
  createRecoveryManager,
  RuntimeDiagnostics,
  RunRegistry,
  createRuntimeDiagnostics,
  apply,
} from 'dhs-multi-agent'
```

The Cordis plugin integration is installed through `apply(ctx, config)` and exposes the orchestration API as `ctx.multiAgent` when the host provides the DSH context.

Example configuration:

```ts
import { apply } from 'dhs-multi-agent'

apply(ctx, {
  concurrency: 4,
  defaultTimeoutMs: 60_000,
})

const result = await ctx.multiAgent.runDag([
  {
    id: 'research',
    agentId: 'researcher',
    prompt: 'Collect the relevant facts.',
  },
  {
    id: 'review',
    agentId: 'critic',
    prompt: 'Review the research result.',
    dependsOn: ['research'],
  },
])

console.log(result)
```

For recovery-oriented orchestration:

```ts
const result = await ctx.multiAgent.runWithRecovery(plan, {
  runId: 'run-1',
  input: 'user intent',
  agents: [
    { id: 'researcher', capabilities: ['research'] },
    { id: 'writer', capabilities: ['writing'] },
  ],
  recovery: { maxAttempts: 3, maxReplans: 2 },
})
```

Recovery is bounded and deterministic. Timeout failures can retry within the attempt budget; unavailable agents can be removed from the run-local routing pool; dependency failures can trigger deterministic replanning; cancellation does not trigger recovery.

## Capabilities

### DAG execution

Independent tasks can execute concurrently while dependencies are preserved. A diamond graph such as `A -> B`, `A -> C`, `B,C -> D` remains a graph rather than being silently serialized.

### Supervisor planning

Supervisor execution follows:

```text
input -> Planner -> Validator -> Router -> Supervisor -> Strategy -> Scheduler -> AgentRunner -> Real DSH
```

The planner produces structured tasks, validation rejects malformed or unsafe plans, and routing assigns explicit or capability-compatible agents.

### Recovery

Recovery is a separate orchestration layer around Supervisor execution. It supports bounded retry, repair, deterministic replan, and abort decisions without making the Supervisor V1 strategy contract more complex.

### Diagnostics and observability

`RuntimeDiagnostics`, `RunRegistry`, metrics collection, and runtime observers provide bounded inspection of active and completed runs without introducing a database requirement.

## DSH integration

The repository contains the bundle patch expected by the Native package:

```text
cordis.patch.yml
```

The Native smoke suite uses the published `@deepseek-ai/*` runtime packages with a scripted adapter and does not require an API key.

## Development

From the repository root:

```bash
pnpm install --frozen-lockfile
pnpm --dir packages/dsh-multi-agent typecheck
pnpm --dir packages/dsh-multi-agent test
pnpm --dir packages/dsh-multi-agent build
pnpm test:smoke
pnpm api:check
pnpm release:contract
```

Release validation also verifies the npm package metadata, distributable files, public exports, package contents, and clean-consumer installation.

## Release model

The Native package is released independently from the Python package surface.

```text
npm-vX.Y.Z
   |
   +-- source-of-truth guard
   +-- typecheck
   +-- Native unit tests
   +-- distributable build
   +-- real-DSH smoke
   +-- release metadata contract
   +-- public API contract
   +-- npm pack / clean-consumer smoke
   `-- npm publish
```

Publishing is gated by CI. Development work does not publish automatically.

## Python runtime

The repository still contains the existing Python multi-agent runtime and its Python API / CLI / HTTP / MCP surfaces under:

```text
src/deepseek_multi_agent_plugin/
```

Python documentation remains available in `docs/` and the historical Python-oriented examples continue to apply to that surface. It is not the source tree for the Native npm package.

## Repository layout

```text
packages/dsh-multi-agent/     Native production source
src/deepseek_multi_agent_plugin/  Python runtime
scripts/                      release and verification guards
docs/                         architecture, API, deployment, and release contracts
cordis.patch.yml              DSH bundle patch
```

## Status

The Native runtime has completed the R13 release-readiness and R14 public-API integrity gates. The next engineering work should build on these verified contracts rather than introducing a second Native implementation path.

## License

MIT
