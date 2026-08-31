# Runtime Capability Matrix

The repository currently ships two runtimes. They share concepts and selected behavioral contracts, but they do not have identical feature sets.

| Capability | Python Runtime | Native DSH Runtime | Status / contract |
|---|---:|---:|---|
| Task / TaskGraph | ✅ | ✅ | Core orchestration |
| Dependency-aware scheduling | ✅ | ✅ | Deterministic dependency semantics |
| Sequential | ✅ | ✅ | Stable |
| Broadcast | ✅ | ✅ | Stable |
| Relay | ✅ | ✅ | Stable |
| Supervisor | ✅ | ✅ | Native E1/E2 contract |
| Planner | ✅ | ✅ | Native Planner V1 is deterministic |
| Capability Router | ✅ | ✅ | Deterministic V1 |
| Retry / Recovery | ✅ | ✅ | Native E4 deterministic V1; R4 exposes the RecoveryManager through the public plugin API |
| Real DSH Runtime | — | ✅ | Native-only |
| Debate | ✅ | ⏭️ | Future Native strategy evolution |
| Consensus | ✅ | ⏭️ | Future Native strategy evolution |
| HTTP adapter | ✅ | ⏭️ | Python-facing surface |
| MCP stdio adapter | ✅ | ⏭️ | Python-facing surface |
| CLI | ✅ | ⏭️ | Python-facing surface |
| Native DSH plugin bundle | — | ✅ | `packages/dsh-multi-agent` |
| True DAG parallel execution | ✅ | ✅ | R3 direct DAG capability via Scheduler; does not modify frozen Supervisor strategy kinds |

## Native architecture boundary

Native keeps the verified Supervisor Strategy Contract:

```text
Broadcast / Sequential / Relay
```

R3 adds a separate Runtime capability for arbitrary dependency graphs:

```text
Planner -> Validator -> Router -> Scheduler -> AgentRunner -> Real DSH
```

This path preserves dependency edges and allows independent branches to execute concurrently under the Scheduler's configured concurrency limit. It is exposed through `runDag()` and the Planner integration `planAndRunDag()`.

R4 exposes deterministic bounded recovery as a separate orchestration boundary:

```text
Plan -> RecoveryManager -> validate -> route -> Supervisor -> Strategy -> Scheduler -> AgentRunner -> Real DSH
                         ↘ retry / repair / replan / abort
```

The public plugin API exposes `recoveryManager()` and `runWithRecovery()`. Recovery policy is finite by construction; cancellation is terminal, timeouts may retry within the attempt budget, agent-unavailable failures may be repaired by rerouting, and dependency failures may trigger deterministic replanning.

The direct DAG and recovery paths deliberately do not redefine `StrategyKind` or mutate the frozen Supervisor V1 contract. Future strategy evolution can build on these capabilities without breaking the existing Supervisor compatibility boundary.

## Release interpretation

When a feature is marked `⏭️`, it is not a missing implementation inside the validated Native path. It is a deliberate scope boundary and must not be inferred as a regression in the Python runtime.
