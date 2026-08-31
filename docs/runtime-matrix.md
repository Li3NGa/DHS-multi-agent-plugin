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
| Retry / Recovery | ✅ | ✅ | Native E4 deterministic V1, explicit RecoveryManager API |
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

The direct DAG path deliberately does not redefine `StrategyKind` or mutate the frozen Supervisor V1 contract. Future strategy evolution can build on this capability without breaking the existing Supervisor compatibility boundary.

## Release interpretation

When a feature is marked `⏭️`, it is not a missing implementation inside the validated Native path. It is a deliberate scope boundary and must not be inferred as a regression in the Python runtime.
