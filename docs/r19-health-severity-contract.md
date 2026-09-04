# R19 Runtime Health Severity Contract

## Problem

Runtime metrics are cumulative by design. A historical timeout or failure should remain visible for diagnostics, but it should not permanently classify a healthy process as `unhealthy`.

## Severity model

`RuntimeDiagnostics.health()` now uses the following rule:

- `healthy`: no active run and no recorded runtime degradation signals;
- `degraded`: historical task/recovery failures, historical recovery timeouts, or active runs without an active failure;
- `unhealthy`: at least one currently active run has one or more recorded recovery failures.

The full cumulative metrics snapshot remains unchanged, so dashboards and post-run analysis still retain historical failure counts.

## Public API

`RunRegistry.activeFailureCount()` exposes the current active-failure signal used by the health classifier. The Native public API guard verifies this member on the built package entrypoint.

## Scope

R19 changes diagnostics classification only. It does not alter scheduling, AgentRunner behavior, recovery decisions, task execution, or package installation semantics.
