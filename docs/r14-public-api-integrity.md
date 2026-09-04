# R14 Public API Integrity

## Objective
Prevent a build from publishing a package whose runtime entrypoint no longer exposes the verified Native public API.

## R14-01 Public API guard
The release entry must expose these stable runtime symbols:

- `apply`
- `AgentRunner`
- `Scheduler`
- `runDag`
- `createSupervisor`
- `createRecoveryManager`
- `RuntimeDiagnostics`
- `RunRegistry`
- `createRuntimeDiagnostics`

The guard checks the built JavaScript entrypoint, not source-only exports.

## R14-02 Gate integration
- Run after the distributable build in Native Runtime CI.
- Run before `npm pack` / `npm publish` in the Native npm release workflow.
- Keep the existing type, unit, build, Real DSH, package, security and consumer gates unchanged.

## R14-03 Scope
No runtime algorithm or public API semantics are changed by R14. The purpose is detection: a missing export fails the gate before release.
