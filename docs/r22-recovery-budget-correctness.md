# R22 — Recovery attempt budget correctness

Recovery actions are only executable when another Supervisor attempt remains in
budget. `maxAttempts` counts real Supervisor executions for one logical run.

Therefore:

- retry requires `canAttempt(attempt + 1)`;
- repair requires `canAttempt(attempt + 1)` because a repaired plan must be
  executed to have any effect;
- replan requires `canAttempt(attempt + 1)` for the same reason;
- when no attempt remains, the last failure is terminal and the final decision is
  `failed` (or `timeout` at the run-status layer).

A repair/replan decision is never recorded for a candidate that will not actually
be dispatched. This keeps the decision trail consistent with real execution.
