# R5 Production Hardening

## Goal

Move the Native orchestration runtime from feature-complete to production-hardened by fixing cross-layer correctness gaps, making cancellation/timeout semantics consistent, and adding package-level regression gates.

## Execution order

1. **Recovery identity correctness (P1)**
   - Map strategy task IDs back to Planner task IDs using the exact task order used by the selected Supervisor strategy.
   - Add a regression test where Planner declaration order differs from topological execution order.

2. **Timeout semantic convergence (P1/P2)**
   - Treat returned `TIMEOUT` and thrown `SupervisorTimeoutError` identically in Recovery.
   - Validate all public run-level `timeoutMs` inputs as finite values greater than zero.

3. **Abortable recovery delay (P2)**
   - Make inter-attempt delay interruptible by the caller's AbortSignal.
   - Guarantee cancellation does not wait for the configured retry delay.

4. **Cross-layer regression coverage (P1/P2)**
   - Recovery + reordered DAG.
   - Thrown timeout recovery.
   - Invalid timeout rejection.
   - Abort during retry delay.

5. **Published-package confidence (P2)**
   - Add a CI consumer smoke test that packs the root Native package, installs the tarball in a clean temporary project, and verifies its public module exports.

6. **Acceptance gate**
   - Native source-of-truth guard.
   - Typecheck.
   - Unit tests.
   - Native bundle build.
   - Real DSH smoke.
   - Python matrix/lint remains green.
   - Consumer package smoke passes.

## Explicit non-goals

This phase does not add new orchestration strategies, databases, dashboards, or LLM-driven planning. The Supervisor contract remains frozen and Recovery remains outside the Supervisor boundary.
