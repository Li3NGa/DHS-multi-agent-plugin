# DSH Integration Plan

> Status: architecture/design only. No core runtime migration is performed by this document.
>
> Repository baseline: `b9e0c62e7d16ba44630bf6a1bc57826534108062` (`fix(supervisor): strict TaskPlan validation/repair pipeline`, 2026-08-21).
>
> Target: migrate the project from a self-hosted Python multi-agent runtime into a native DeepSeek Harness (DSH) / Cordis plugin, while keeping the existing Python runtime as the behavioral reference during migration.

## 0. Executive decision

The current project should **not** be ported line-by-line to TypeScript.

The correct migration boundary is:

```text
Current Python Runtime
    |
    |  behavior/reference only
    v
Multi-Agent Policy Layer
    |
    |  native DSH implementation
    v
Cordis Plugin
    |
    +--> ctx.agents
    +--> ctx.sessions
    +--> ctx.llm
    +--> ctx.tools
    +--> agent/* events
    +--> session/event
    +--> Cordis lifecycle/configuration
```

The Python implementation currently owns both **multi-agent policy** and a large amount of **generic runtime infrastructure**. DSH already owns the generic agent/session/LLM/tool/plugin lifecycle. The migration should therefore preserve the former and delete/rely on the latter rather than reproduce it.

DSH's current architecture explicitly defines `ctx.sessions`, `ctx.tools`, `ctx.agents`, `ctx.agentLoop`, and `ctx.llm` as core capability seams. The default agent loop is the concrete loop implementation; extensions are expected to be plugins over its events and services. [DSH architecture](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md)

---

## 1. DSH 提供的能力

### 1.1 Cordis plugin lifecycle

A DSH plugin is a Cordis plugin with an `apply(ctx, config)` entry point. Dependencies are declared with `inject`; Cordis waits for required services before activation. Plugin registrations are lifecycle effects and are automatically removed when the plugin unloads. External resources must use `ctx.effect()` with a disposer.

Relevant native mechanisms:

- `export const name`
- `export const inject`
- `export const Config`
- `export function apply(ctx, config)`
- `ctx.plugin(...)`
- `ctx.on(...)`
- `ctx.effect(...)`
- plugin Fiber lifecycle and disposal
- configuration validation and HMR/restart semantics

Therefore the new plugin must not invent its own plugin lifecycle, cleanup registry, service dependency mechanism, or configuration loader.

### 1.2 Agent Registry — `ctx.agents`

DSH exposes the public Agent contract and live registry independently from the concrete loop.

Relevant operations include:

- `ctx.agents.create(...)`
- `ctx.agents.resume(...)`
- `ctx.agents.register(...)`
- `ctx.agents.get(id)`
- `ctx.agents.list()`
- `ctx.agents.roots()`
- `ctx.agents.isOwnedBy(...)`
- `AgentHandle.dispose()`

The registry also carries agent initiator scope through asynchronous work.

This replaces the Python project's process-local agent registry and most of the agent ownership/lifecycle machinery.

### 1.3 Agent Loop

`@deepseek-ai/dsh-agent-loop` is the default concrete implementation of the `Agent` interface. It owns the turn/step execution loop:

```text
turn/start
  -> claim inbox input
  -> agent/pre-step
  -> step/start
  -> agent/request
  -> ctx.llm / llm/stream
  -> tool calls through ctx.tools
  -> step/end
  -> continuation or turn/end
```

The loop already owns:

- queued user/steering/injected input
- turn and step lifecycle
- cancellation signal propagation
- request derivation
- LLM dispatch
- tool dispatch
- session event emission
- agent status/lifecycle
- idle/quiescence semantics

The plugin should **orchestrate Agents**, not implement another loop.

### 1.4 `ctx.sessions`

DSH sessions are event-sourced append-only logs. Model history is derived from session events instead of being maintained as a separate custom conversation store.

Native responsibilities include:

- session creation
- session identity
- append-only event log
- replay/fork primitives
- event sequencing
- session lifecycle
- model-history derivation
- optional persistence through `ctx.sessionPersistence`
- `session/event` observation
- explicit `ctx.sessions.flush()` durability barriers where applicable

The Python `SessionManager` must therefore not be recreated in the native plugin.

### 1.5 `ctx.llm`

DSH defines an LLM adapter seam. The agent loop consumes the provider-neutral LLM service, while adapters such as DeepSeek-specific providers implement the actual model route.

The native stack therefore owns:

- message vocabulary
- stream vocabulary
- model request configuration
- provider/adapter selection
- streaming
- request errors
- adapter defaults
- model-visible history derivation

The migrated multi-agent layer should not contain a DeepSeek HTTP client or generic OpenAI-compatible HTTP client unless it is implementing a genuinely new DSH LLM adapter.

### 1.6 `ctx.tools`

DSH owns the scoped tool registry and tool execution pipeline.

The native pipeline includes:

```text
tools/pre-execute
    -> tools/execute
    -> tools/post-execute
    -> finalizeContent
    -> tools/result
```

Tools registered through `ctx.tools.register()` are automatically scoped to the plugin/agent lifecycle.

This replaces any custom tool registry, tool lifecycle, tool timeout wrapper, or tool execution transport that the Python runtime currently owns.

### 1.7 Events

Events are the primary DSH extension surface.

For this project the most important events are:

| Event | Role for Multi-Agent plugin |
|---|---|
| `agent/created` | discover newly available agents |
| `agent/disposed` | remove orchestration state for an agent |
| `agent/status` | observe lifecycle/status transitions |
| `agent/session-start` | initialize per-agent orchestration state |
| `agent/inbox/inserted` | observe queued work |
| `agent/inbox/claimed` | observe work admitted to a step |
| `agent/pre-step` | policy gate/rewrite for a proposed step |
| `agent/request` | request-policy / route customization |
| `agent/request-error` | retry/repair policy at the model-request boundary |
| `agent/turn-stopping` | continuation policy before a turn closes |
| `agent/error` | observe terminal agent errors |
| `session/event` | durable transcript/telemetry source |
| `tools/pre-execute` etc. | optional multi-agent tool policy |

The distinction is critical: `agent/*` is live coordination; `session/event` is durable history.

### 1.8 Plugin configuration

DSH plugin configuration is declared in the plugin and supplied through `cordis.yml` / patch configuration. Schemastery validates configuration at load/update time.

Configuration should describe deployment policy, not duplicate runtime internals.

---

## 2. 当前 Python 项目重复实现的能力

The current Python baseline contains substantial infrastructure that DSH already provides.

| Python capability | Current location | DSH replacement | Migration decision |
|---|---|---|---|
| Agent registry | `agents.py`, `coordinator.py` | `ctx.agents` | Remove from native design |
| Agent lifecycle | `agents.py`, coordinator/runtime code | Agent + `AgentHandle` + Cordis lifecycle | Remove |
| Session registry / TTL / LRU | `sessions.py` | `ctx.sessions` + persistence/query plugins | Remove |
| Conversation memory store | `memory.py`, `context.py` | `ctx.sessions` event log + derived messages | Remove |
| LLM HTTP client | `agents.py` / provider implementations | `ctx.llm` + DSH LLM adapters | Remove; use native adapter |
| Provider abstraction | `agents.py` | DSH LLM service/adapter seam | Remove from core plugin |
| Tool transport | MCP/HTTP adapters | DSH `ctx.tools` / native protocol plugins | Remove from native core |
| HTTP API | `adapters/http.py` | DSH UI/API/SDK composition as appropriate | Remove from native core |
| MCP server | `adapters/mcp.py` | DSH tools/protocol surfaces | Remove from native core |
| CLI transport | `adapters/cli.py` | DSH CLI/plugin composition | Remove from native core |
| Plugin lifecycle | implicit Python process/runtime | Cordis Fiber lifecycle | Remove |
| Config parsing | `config.py`, YAML loading | Cordis plugin `Config` + patch config | Remove |
| Shared executor/thread pool | `runtime/executor.py` | DSH Agent loop / Jobs / workflow plugins where applicable | Remove unless a specific policy requires a new worker seam |
| Task deadline machinery | `runtime/deadline.py`, scheduler | Agent cancellation + DSH policy/plugin boundaries | Re-evaluate; do not port wholesale |
| Run cancellation token | `runtime/context.py`, scheduler | `AbortSignal` / Agent cancellation / Fiber disposal | Remove generic implementation |
| Run history/trace registry | `history.py`, `observability.py` | session events + DSH telemetry/observability plugins | Remove generic implementation |
| Cache | `cache.py` | DSH provider/runtime caching where available; otherwise narrow policy only | Remove generic cache first |
| Security/RBAC for HTTP | `security.py`, HTTP adapter | DSH host/client permissions and protocol layer | Remove from native core |
| HTTP/MCP rate limiting | adapters/runtime | DSH host/protocol mechanisms | Remove |

The repository itself confirms that the Python implementation currently combines adapters, coordinator, strategies, scheduler, budgets, sessions, cache, observability and security in one runtime. fileciteturn9file0

The latest Python changes also demonstrate that the project has invested heavily in runtime semantics—cooperative cancellation, three distinct deadline types, bounded scheduling, strict TaskPlan validation and a repair pipeline. Those behaviors are valuable as **migration acceptance criteria**, but the underlying mechanisms should not automatically be ported. fileciteturn6file0 fileciteturn13file0

---

## 3. 应该保留的 Multi-Agent 独有能力

The following are the actual product value of this repository and should become the native DSH plugin's domain layer.

### 3.1 Collaboration strategies

Keep the six collaboration policies:

1. `broadcast`
2. `sequential`
3. `debate`
4. `supervisor`
5. `consensus`
6. `relay`

These are not generic agent-runtime capabilities. They describe **how multiple DSH Agents collaborate**.

The Python implementation already provides these as separate strategy functions, with deterministic broadcast result ordering now explicitly fixed. fileciteturn12file0

### 3.2 Structured Supervisor TaskPlan

Keep:

- JSON TaskPlan schema
- task identity
- task description
- explicit agent assignment
- capability requirements
- `depends_on`
- strict validation
- bounded repair
- semantic-preservation rule
- failure on unrepaired invalid plans

Do not keep the Python parser/executor implementation itself.

The current supervisor pipeline is explicitly:

```text
parse -> TaskPlan -> validate -> repair -> validate -> execute
```

and deliberately refuses to erase dependency edges merely to make an invalid plan executable. That semantic rule should become a TypeScript invariant/test suite. fileciteturn13file0

### 3.3 DAG orchestration policy

Keep the **DAG as a collaboration abstraction**, not as a second task runtime.

Required semantics:

- independent tasks may execute concurrently
- dependencies gate admission
- downstream tasks do not execute after an invalid prerequisite
- terminal task states are explicit
- run-level cancellation propagates to pending/running collaboration work
- result ordering is deterministic where it is part of the public strategy contract

The implementation should first evaluate whether DSH workflow/jobs/subagent facilities can express the DAG before introducing any new scheduler service.

### 3.4 Capability-based routing

Keep:

```text
explicit agent > capability match > deterministic fallback
```

Capabilities belong to the **multi-agent policy domain**. The DSH Agent registry owns identities; this plugin owns the meaning of capability-based assignment.

### 3.5 Supervisor repair policy

Keep only repairs that preserve task semantics:

- unknown agent -> valid worker
- unsupported capability -> remove only the unsatisfiable routing constraint
- dependency errors/cycles -> reject or request a new plan
- never silently delete dependencies

### 3.6 Deterministic collaboration output

Broadcast/debate/consensus outputs need stable participant ordering even when underlying execution is concurrent.

Concurrency and presentation order must remain separate concerns:

```text
execute concurrently
        |
        v
collect by logical participant/task order
        |
        v
compose deterministic transcript/result
```

This is a behavior contract, not a thread-pool feature.

### 3.7 Multi-agent state machine

Keep a narrow domain state model for orchestration runs if needed:

```text
PLANNED -> RUNNING -> SUCCEEDED
                   -> FAILED
                   -> CANCELLED
```

This state must describe a **collaboration run**, not duplicate DSH Agent/Session status.

### 3.8 Optional policies that survive only if DSH has no native equivalent

These require explicit justification before implementation:

- collaboration-specific budget policy
- collaboration-specific deadline policy
- strategy-level retry/repair policy
- run-level aggregation
- evaluator/judge selection
- cross-agent result normalization

They should be small Cordis plugins or pure policy modules, not a replacement runtime.

---

## 4. 应该移除的基础设施

The migration target must not reproduce these as native DSH infrastructure.

### Remove / do not port

- Python `Agent` base runtime and provider hierarchy
- custom Agent Registry
- custom SessionManager
- custom memory/context runtime
- custom LLM HTTP clients
- custom provider fallback runtime
- shared Python thread pool
- generic scheduler runtime
- custom cancellation-token tree
- generic task/run deadline implementation
- custom HTTP server
- custom MCP server
- custom CLI transport
- custom RBAC layer for the HTTP server
- custom run-history storage
- custom trace registry
- generic cache runtime
- custom configuration parser/loader
- Python plugin installation/runtime bridge

### Keep only as migration references

The following Python modules remain useful during migration because they encode behavior that tests can compare against:

- `strategies.py`
- `supervisor.py`
- `runtime/task.py`
- `runtime/dependency.py`
- selected scheduler behavior tests
- selected broadcast/debate/consensus/relay tests

They are **reference implementations**, not target architecture.

The existing `dsh/` directory is also not the target architecture: it currently describes installing the Python package as an MCP server and mounting `mcp-multiagent` into a DSH profile. That is an integration bridge, not a native Cordis plugin. fileciteturn5file0

---

## 5. Python → DSH 迁移映射

| Python concept | Native DSH concept | Notes |
|---|---|---|
| `AgentCoordinator` | Cordis plugin + pure orchestration service/module | Coordinator should become policy, not runtime owner |
| `register_agent()` | `ctx.agents.register()` / `ctx.agents.create()` | Prefer native Agent identities |
| `Agent.handle()` | `Agent.followup()` / `steer()` / `inject()` and normal loop | Do not invoke providers directly |
| provider/model | `ctx.llm` adapter route | Do not create a parallel provider stack |
| `session_id` | `SessionId` / `ctx.sessions` | Native identity |
| `SessionManager` | `ctx.sessions` + persistence/query plugins | No duplicate TTL/LRU manager |
| `memory` / transcript | `session/event` | Durable source of truth |
| context assembly | `ctx.systemPrompt` + session-derived history | Only strategy-specific context remains in plugin |
| `broadcast` | orchestration plugin over multiple `Agent`s | Parallel admission + deterministic collection |
| `sequential` | orchestration policy | Feed output through Agent API |
| `debate` | orchestration policy + judge Agent | Judge is an ordinary DSH Agent |
| `supervisor` | orchestration policy + TaskPlan | Task execution delegates to native Agents/workflows |
| `consensus` | orchestration policy + vote/judge aggregation | No provider runtime |
| `relay` | orchestration policy | Same Agent/session or separate child Agents depending contract |
| `WorkerRouter` | pure TypeScript policy module | Query `ctx.agents.list()` and plugin-owned capability metadata |
| `TaskPlan` | domain TypeScript type + schema | Keep strict validation |
| DAG scheduler | DSH workflow/jobs/subagent primitives where sufficient; otherwise narrow orchestration module | Do not create generic executor first |
| cancellation token | `AbortSignal`, `Agent.cancel()`, `AgentHandle.dispose()` | Map semantics carefully |
| run deadline | collaboration policy using signal/deadline | Must not fight Agent loop cancellation |
| provider timeout | DSH LLM/tool policy | Never wrap all LLM calls in another client timeout without reason |
| budget | DSH token meter / policy plugins where possible; collaboration budget only if needed | Avoid double accounting |
| observability Trace | `session/event` + DSH telemetry | Add only collaboration-specific events if necessary |
| HTTP `/run` | DSH host/API/UI composition | Not part of native plugin core |
| MCP `run` | DSH tool registration / protocol bridge | Prefer model-facing DSH tools |
| YAML config | Cordis plugin `Config` + `cordis.yml` | Schema validated by Cordis |
| plugin install script | npm package + Cordis patch/config | Native distribution |

---

## 6. 推荐的 TypeScript 项目结构

Recommended target structure:

```text
packages/
  dsh-multi-agent/
    package.json
    tsconfig.json
    README.md
    src/
      index.ts                 # Cordis plugin entry: name/inject/Config/apply
      types.ts                 # public domain types
      config.ts                # Schemastery config

      strategies/
        index.ts
        broadcast.ts
        sequential.ts
        debate.ts
        supervisor.ts
        consensus.ts
        relay.ts

      task-plan/
        schema.ts               # TaskPlan runtime schema
        validate.ts             # strict structural validation
        repair.ts               # bounded semantic-safe repair
        types.ts

      orchestration/
        run.ts                  # collaboration-run state, not agent runtime
        router.ts               # capability/agent routing
        dag.ts                  # DAG policy only
        cancellation.ts         # mapping to AbortSignal/Agent cancellation
        aggregation.ts          # deterministic result composition

      events.ts                 # optional plugin-owned event declarations
      tools.ts                  # only if model-facing DSH tools are needed
      service.ts                # optional Service only if shared plugin API needs it

    tests/
      strategies/
      task-plan/
      orchestration/
      integration/
```

### Structural rules

1. `src/index.ts` owns Cordis integration only.
2. Strategy modules are pure orchestration policy where possible.
3. No module may create its own LLM HTTP client.
4. No module may create a second Agent loop.
5. No module may create a global process-wide Agent registry.
6. No module may persist conversation history outside `ctx.sessions` unless the data is explicitly non-conversational domain state.
7. No module may create a replacement for `ctx.tools`.
8. All external resources must be lifecycle-owned by Cordis.
9. `inject` must list hard dependencies; optional services should use `ctx.get(...)` when appropriate.
10. Configuration must be validated by a Cordis-compatible schema.

### Recommended dependency direction

```text
Cordis entry
    |
    +--> DSH services
    |      ctx.agents
    |      ctx.sessions
    |      ctx.llm
    |      ctx.tools (optional)
    |
    +--> orchestration policy
            |
            +--> strategies
            +--> TaskPlan
            +--> routing
            +--> DAG policy
            +--> result aggregation
```

The orchestration layer must never depend downward on a custom runtime abstraction merely to make the migration look similar to Python.

---

## 7. 分阶段迁移方案

### Phase 0 — Architecture freeze (current phase)

Deliverable:

- `docs/dsh-integration-plan.md`

Rules:

- no Python runtime changes
- no TypeScript runtime implementation
- no HTTP/MCP additions
- no new strategy/provider/session/memory runtime

Exit condition: architecture and ownership boundaries are agreed.

### Phase 1 — Native plugin skeleton

Create only:

- npm package metadata
- TypeScript build
- `src/index.ts`
- Cordis `name`
- `inject`
- validated `Config`
- minimal `apply(ctx, config)`
- smoke test proving load/unload works

No strategy implementation yet.

### Phase 2 — Agent/session integration

Implement the smallest adapter around:

- `ctx.agents.list()` / `get()` / `create()` as required
- `ctx.sessions`
- `ctx.llm`
- `agent/*` lifecycle events
- `session/event`

Prove that one native DSH Agent can participate without any Python runtime.

### Phase 3 — Broadcast + sequential

Migrate the least stateful strategies first.

Acceptance criteria:

- native Agents only
- concurrent execution where appropriate
- deterministic result ordering
- cancellation follows DSH semantics
- no custom session store
- no custom provider client

### Phase 4 — Debate + relay + consensus

Migrate strategies that require multi-round state and judge/aggregation logic.

Use DSH sessions as the transcript source. Keep only strategy-specific state outside the session log.

### Phase 5 — Supervisor + TaskPlan

Port the domain contract:

```text
parse
  -> strict validate
  -> bounded semantic-safe repair
  -> validate again
  -> execute
  -> deterministic aggregate
```

The Python tests become behavior fixtures for the TypeScript implementation.

Critical invariant: dependency errors/cycles are not silently removed.

### Phase 6 — DAG execution integration

Before writing a scheduler, evaluate:

1. DSH workflow APIs
2. DSH jobs APIs
3. subagent in-process facilities
4. ordinary Agent handles + `whenIdle()`

Only introduce a dedicated DAG execution module if these primitives cannot express the required dependency semantics.

If a new module is required, it should be a **DAG policy coordinator**, not a replacement executor/thread pool.

### Phase 7 — Native DSH tools and UX

Expose model-facing controls only after the domain core is stable.

Potential tools:

- start collaboration
- inspect collaboration status
- inspect task plan
- cancel collaboration
- inspect agent/team capabilities

Tools should be registered with `ctx.tools` and remain scoped to the plugin.

### Phase 8 — Compatibility / deprecation

Freeze the Python runtime as a compatibility/reference implementation.

Then:

- document native DSH installation
- mark MCP/HTTP Python bridge as compatibility/deprecated
- provide behavior parity fixtures
- migrate examples
- only later remove Python runtime if a major-version policy permits it

---

## 8. 风险

### 8.1 DSH developer-preview churn

DSH explicitly states that it is in developer preview and may introduce compatibility-breaking changes. The native package must therefore isolate direct DSH API usage inside a thin integration layer.

Mitigation:

- keep `src/index.ts` and DSH service adapters small
- avoid reaching into DSH private implementation
- depend on public package contracts/events
- maintain a DSH compatibility matrix in CI

### 8.2 Double runtime ownership

The biggest architectural risk is accidentally keeping the Python-style runtime while adding a Cordis facade.

Bad target:

```text
DSH Agent
   |
Python-like Coordinator
   |
Python-like Scheduler
   |
Python-like Provider
```

Correct target:

```text
DSH Agent / Session / LLM / Tools
            |
     Multi-Agent Policy
```

### 8.3 Cancellation semantic mismatch

Python currently distinguishes task deadline, run deadline and provider timeout and has cooperative cancellation. DSH has its own Agent cancellation and `AbortSignal` semantics.

Do not translate these mechanically. Define which layer owns each cancellation decision.

Recommended ownership:

- Agent cancellation -> DSH Agent
- provider/model cancellation -> `AbortSignal` supplied by DSH loop
- collaboration cancellation -> plugin-owned controller that propagates to child Agent handles
- deadline policy -> plugin policy, implemented using DSH signals

### 8.4 Session duplication

Maintaining a Python-style memory object beside `ctx.sessions` would create two sources of truth.

Mitigation: model-visible collaboration state must be reconstructible from DSH session events. Ephemeral scheduler bookkeeping may remain in memory.

### 8.5 Event misuse

Using `agent/*` events as durable history would be incorrect. Using `session/event` for live control decisions without understanding durability could also create races.

Mitigation: live coordination uses `agent/*`; durable facts use `session/event`.

### 8.6 Overusing `inject`

Declaring every service as mandatory can unnecessarily couple the plugin to a specific DSH composition.

Mitigation: use `inject` for hard requirements; use `ctx.get()` for optional capabilities where supported.

### 8.7 HMR / unload races

Native DSH plugin unload is asynchronous and lifecycle-owned. Collaboration work started by the plugin must stop or reach a defined quiescence boundary when the plugin unloads.

Mitigation:

- keep owned AgentHandles
- dispose them during plugin cleanup
- use `ctx.effect()` for non-Cordis resources
- avoid module-global mutable state

### 8.8 Deterministic ordering under concurrency

Native Agents may complete in arbitrary order. The strategy contract may nevertheless require stable participant/task ordering.

Mitigation: retain logical ordering metadata and aggregate explicitly by declared order.

### 8.9 API churn from DSH package versions

Avoid importing broad root packages solely for convenience. Keep package imports explicit and aligned with current DSH public package boundaries.

---

## 9. API 兼容策略

Compatibility has three layers.

### 9.1 Behavioral compatibility

This is the highest priority.

The TypeScript implementation must preserve the Python behavior that users depend on:

- strategy semantics
- TaskPlan validation
- repair safety rules
- DAG dependency semantics
- deterministic broadcast ordering
- terminal task states
- cancellation outcomes
- result aggregation shape where externally documented

The Python tests should become golden/behavior fixtures rather than architectural constraints.

### 9.2 Domain API compatibility

Keep stable domain concepts where they are useful:

```text
Strategy
TaskPlan
Task
Agent assignment
Capability
CollaborationRun
RunResult
```

Do not preserve Python class names or implementation boundaries merely for source compatibility.

For TypeScript, prefer explicit interfaces/types and discriminated unions.

### 9.3 Transport API compatibility

The current HTTP and MCP APIs should **not** be rebuilt inside the native plugin.

If backward compatibility is required, use a separate thin compatibility bridge:

```text
Legacy client
    |
HTTP/MCP compatibility bridge
    |
DSH multi-agent domain API
    |
ctx.agents / ctx.sessions / ctx.llm
```

The bridge must contain no scheduling, provider, session, or memory logic.

### 9.4 Result compatibility

During migration define a normalized domain result:

```ts
interface CollaborationResult {
  strategy: string
  prompt: string
  final: string
  rounds: RoundResult[]
  tasks?: TaskResult[]
  meta: {
    agents: string[]
    elapsedMs: number
    usage?: UsageSummary
  }
}
```

The exact final schema should be derived from the existing documented Python API before Phase 3, rather than invented during implementation.

### 9.5 Versioning

Recommended:

- Python package: compatibility/reference line
- native DSH plugin: independent semantic version
- breaking DSH API changes: plugin major/minor compatibility matrix
- transport bridge: deprecation window before removal

Do not promise long-term binary compatibility against DSH while DSH remains developer-preview software.

---

## 10. Phase acceptance criteria

A migration phase is complete only when all applicable criteria are true:

- no duplicate DSH-owned infrastructure was introduced
- Cordis lifecycle cleanup passes unload/HMR tests
- hard dependencies are declared with `inject`
- configuration is schema-validated
- model-visible state comes from DSH sessions
- LLM calls use `ctx.llm`
- Agent execution uses `ctx.agents` / native Agent handles
- tool execution uses `ctx.tools` where tools are required
- cancellation does not create an independent runtime
- concurrency does not require a global custom thread pool
- strategy output ordering is deterministic where required
- Python behavior fixtures remain green for the migrated strategy

---

## 11. Current baseline assessment

As of commit `b9e0c62`, the repository is a mature Python multi-agent runtime rather than a native DSH plugin. The latest commits explicitly cover scheduler cancellation/deadline semantics and strict supervisor plan validation/repair, while the repository remains Python-based and exposes Python API, CLI, HTTP and MCP transports. fileciteturn9file0

The existing `dsh/` installation path is an MCP bridge into DSH, not Cordis-native integration. fileciteturn5file0

The target should therefore be treated as an **architecture migration**, not a Python-to-TypeScript syntax conversion.

The first implementation milestone after this document should be a minimal Cordis plugin that consumes DSH's native Agent/Session/LLM services. Only after that boundary is proven should the six collaboration strategies be migrated one by one.

---

## References

Primary DSH references used for this plan:

- DeepSeek Harness architecture: `docs/architecture.md`
- Cordis first plugin: `docs/cordis-tutorial/01-first-plugin.md`
- Cordis lifecycle/effects: `docs/cordis-tutorial/02-lifecycle-and-effects.md`
- Cordis services: `docs/cordis-tutorial/03-services.md`
- Plugin configuration: `docs/user/develop/basic/config.md`
- Agent service: `packages/core/agent/README.md`
- Agent loop: `packages/core/agent-loop/README.md`
- Sessions: `docs/subsystems/session.md`
- Event producer/consumer matrix: `docs/event-producer-consumer.md`
- Capability seams: `docs/capability-seams.md`
- Extension cookbook: `docs/cookbook/extension-cookbook.md`

DSH developer-preview status and compatibility warning should be checked again before each migration phase because the project is evolving rapidly.
