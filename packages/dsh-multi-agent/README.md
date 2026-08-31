# DSH Multi-Agent Orchestration (Native)

This package is the **production Native source tree** for the DeepSeek Harness (DSH) Cordis plugin.

Production source:

```text
packages/dsh-multi-agent/src/
```

The Python runtime remains under `src/deepseek_multi_agent_plugin/` for its existing Python API / CLI / HTTP / MCP surface. The historical `dsh-native/` tree is verification-only; see `docs/source-of-truth.md`.

## Native structure

```text
src/
  task.ts
  graph.ts
  dsh.ts
  runner.ts
  scheduler.ts
  planner/
    planner.ts
    validator.ts
    router.ts
    integration.ts
  supervisor/
    supervisor.ts
    lifecycle.ts
    strategy.ts
    errors.ts
    types.ts
  recovery/
    failure.ts
    retry-policy.ts
    repair.ts
    replanner.ts
    manager.ts
  strategies/
    sequential.ts
    relay.ts
    broadcast.ts
    dag.ts
    contract.ts
  index.ts
```

The Native execution paths are now:

```text
Supervisor path:
input
  -> Planner
  -> Validator
  -> Router
  -> Supervisor
  -> Strategy
  -> Scheduler
  -> AgentRunner
  -> Real DSH
  -> Recovery (when explicitly orchestrated)

Arbitrary-DAG path:
input
  -> Planner
  -> Validator
  -> Router
  -> Scheduler
  -> AgentRunner
  -> Real DSH
```

## Development

Run from the repository root:

```bash
pnpm install --frozen-lockfile
pnpm --dir packages/dsh-multi-agent typecheck
pnpm --dir packages/dsh-multi-agent test
pnpm --dir packages/dsh-multi-agent build
pnpm test:smoke
```

The package test and smoke suites validate the package source tree. The release entry is built by the root package into `dist/index.js`, with DSH runtime packages externalized so the host supplies them.

## DSH integration

Use the root `cordis.patch.yml` or the example under this package. The real-DSH smoke suite uses the published `@deepseek-ai/*` runtime packages and a scripted adapter without an API key.

## Current Native V1 boundaries

Native V1 keeps the verified Supervisor Strategy Contract:

- `sequential`
- `broadcast`
- `relay`

R3 adds a **direct DAG execution capability** through `runDag()` and `planAndRunDag()`. Arbitrary dependency graphs are preserved and executed by the existing Scheduler, so independent branches may run concurrently instead of being forced into a topological linearization.

The direct DAG path deliberately does not extend `StrategyKind` or modify the frozen Supervisor V1 contract. This keeps the Supervisor compatibility boundary stable while exposing the Runtime's actual DAG capability.

No LLM Planner, database, dashboard, Debate or Consensus implementation is part of the current Native production path.
