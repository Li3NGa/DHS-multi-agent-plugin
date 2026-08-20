# ADR 0002: Run deadline float alignment and run_binds comparison

- Status: accepted
- Date: 2026-08-21

## Context

`clamp_timeout()` returns `deadline - time.monotonic()` bounded by the
per-call timeout. With a large monotonic clock, this subtraction carries
float tail error up to ~1e-13, so a test asserting `clamp_timeout(5.0) <=
0.3` after `start_run_deadline(0.3)` could observe `0.3000000000001819`.

Quantizing the returned remaining time fixes the assertion, but any
downward quantization (e.g. `math.floor` to ms) breaks the invariant
strategies rely on: `run_binds` decided by
`run_dl - time.monotonic() <= timeout` flips to False when the timeout was
shrunk by more than the time elapsed between the two readings, and the run
deadline no longer aborts the wait.

## Decision

1. `clamp_timeout()` quantizes `remaining` to microseconds
   (`round(remaining, 6)`), eliminating the visible float tail while
   keeping the quantization loss (~0.5us) far below the decision margin.
2. `run_binds` compares absolute clock readings instead of two independent
   subtractions: `run_dl <= time.monotonic() + timeout + 1e-6` (and the
   parallel equivalent for the wait deadline). The 1us tolerance absorbs
   the float tail of `now + timeout`.

## Consequences

- The run deadline reliably aborts waits (`RunTimeout`) when it expires
  before the per-call timeout.
- Per-call timeouts shorter than the run deadline still return
  `{"error": "timeout"}` unchanged.
- The 1us tolerance can only flip the decision when a per-call timeout and
  the run deadline are within 1us of each other — negligible in practice.
