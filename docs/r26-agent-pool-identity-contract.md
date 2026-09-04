# R26 — Agent pool identity contract

`AgentRouter` treats `AgentDescriptor.id` as the stable identity used by
explicit routing, round-robin assignment, Scheduler per-agent serialization,
and recovery quarantine.

Therefore a routing pool must contain only non-empty, unique agent IDs.
Constructing `AgentRouter` with an empty ID or a duplicate ID fails immediately
with `PlanRoutingError`.

This prevents two descriptors from aliasing the same logical agent and avoids
ambiguous routing or accidental serialization across apparently different pool
entries.
