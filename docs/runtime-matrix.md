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
| Retry / Recovery | ✅ | ✅ | Native E4 deterministic V1 |
| Real DSH Runtime | — | ✅ | Native-only |
| Debate | ✅ | ⏭️ | Future Native strategy evolution |
| Consensus | ✅ | ⏭️ | Future Native strategy evolution |
| HTTP adapter | ✅ | ⏭️ | Python-facing surface |
| MCP stdio adapter | ✅ | ⏭️ | Python-facing surface |
| CLI | ✅ | ⏭️ | Python-facing surface |
| Native DSH plugin bundle | — | ✅ | `packages/dsh-multi-agent` |
| True DAG parallel strategy | ✅ | ⏭️ | Native limitation: current E1 strategy boundary linearizes unsupported DAG shapes |

## Native architecture boundary

Native V1 intentionally supports the verified Strategy Contract:

```text
Broadcast / Sequential / Relay
```

A dependency DAG that cannot be represented by those strategies is deterministically linearized for sequential execution. This means the Planner can represent a DAG while the current Native runtime does not preserve parallelism for every DAG shape. This is a known architecture limitation, not a hidden behavior.

Removing that limitation requires a separate Strategy Boundary evolution with new Scheduler concurrency semantics; it is not part of the current production hardening work.

## Release interpretation

When a feature is marked `⏭️`, it is not a missing implementation inside the already-validated Native V1 path. It is a deliberate scope boundary and must not be inferred as a regression in the Python runtime.
