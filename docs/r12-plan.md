# R12 Stability & Final Production Gate

## Objective
Validate the post-R11 Native runtime under repeated execution and close the final production gate without changing runtime semantics.

## R12-01 Long-run stability
- Reuse the same Scheduler instance across many completed runs.
- Reuse the same Scheduler instance across failure/cancellation runs followed by healthy runs.
- Exercise bounded RuntimeDiagnostics history repeatedly and verify no growth beyond the configured bound.
- Verify every completed run releases active runtime state.

## R12-02 Final regression gate
- Native TypeScript typecheck.
- Native unit tests, including stability tests.
- Native package build.
- Real DSH bundle smoke.
- Release metadata validation.
- Clean consumer package smoke.
- Python lint/type checks and Python 3.10/3.11/3.12/3.13 regression matrix.

## R12-03 Release decision
R12 passes only when all gates above are green on the release candidate commit. No new runtime features are introduced in R12.
