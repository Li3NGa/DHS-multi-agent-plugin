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
    contract.ts
  index.ts
```

The Native execution path is:

```text
input
  -> Planner
  -> Validator
  -> Router
  -> Supervisor
  -> Strategy
  -> Scheduler
  -> AgentRunner
  -> Real DSH
  -> Recovery (when required)
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

Use the root `cordis.patch.yml` or the example under this package. The real-DSh smoke suite uses the published `@deepseek-ai/*` runtime packages and a scripted adapter without an API key.

## Current Native V1 boundaries

Native V1 is intentionally limited to the verified Strategy Contract:

- `sequential`
- `broadcast`
- `relay`

The Planner can describe arbitrary DAG dependencies, but unsupported DAG shapes are deterministically linearized into sequential execution. This is a documented architecture limitation; it is not a reason to fork the current Strategy Contract mid-release.

No LLM Planner, database, dashboard, Debate or Consensus implementation is part of the current Native V1 production path.
