# R23 — Multi-agent repair quarantine contract

When one Supervisor attempt reports multiple `AGENT_UNAVAILABLE` task failures,
Recovery treats every reported unavailable `agentId` as unusable for the next
attempt.

Repair still clears the explicit agent assignment from each affected task so the
Router can reroute them. The routing pool is then filtered against the full set of
unavailable agent IDs observed in that attempt, plus the primary failure agent when
present as a defensive fallback.

This prevents a multi-task broadcast failure from immediately reassigning one of
the known-bad agents and wasting another recovery attempt.
