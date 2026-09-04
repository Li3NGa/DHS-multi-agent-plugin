# R25 — RecoveryManager single-flight contract

`createRecoveryManager()` returns a single-flight wrapper around the deterministic
`RecoveryManager`. One instance may own one active logical run at a time because
it owns one Supervisor instance whose lifecycle is intentionally single-flight.

A concurrent `run()` call is rejected immediately with a lifecycle usage error;
it is not queued and it never starts a second Supervisor run. After the active
run reaches a terminal result or throws, the guard is released in `finally`, so
the same RecoveryManager can be reused sequentially.

This round does not change retry, repair, replan, timeout, cancellation, routing,
or Scheduler semantics. The guard only protects the public factory path from
sharing one Supervisor across overlapping recovery runs.
