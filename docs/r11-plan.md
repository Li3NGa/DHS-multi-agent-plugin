# R11 Production Hardening Plan

## Objective
Harden the R10 runtime diagnostics contract without changing Planner, Scheduler, AgentRunner, or Recovery semantics.

## R11-01 Diagnostics contract hardening
- Treat recovery lifecycle as a state machine.
- Ignore duplicate terminal events after completion.
- Ignore orphan attempt/failure/decision events when no run is active.
- Preserve bounded history and newest-first ordering.
- Preserve payload non-retention guarantees.
- Keep health derived only from bounded runtime signals.

## R11-02 Verification
- Unit tests for lifecycle edge cases and bounded history.
- TypeScript strict typecheck.
- Package build.
- Real DSH smoke test.
- Consumer smoke/regression test.

## Gate
R11 passes only when implementation, tests, typecheck, build, Real DSH smoke, and consumer regression are all green. No new feature work enters R11.
