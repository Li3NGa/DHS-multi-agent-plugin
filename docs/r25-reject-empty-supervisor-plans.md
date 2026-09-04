# R25 — Non-empty Supervisor plan contract

A Supervisor run represents one actual multi-agent execution and must contain at
least one executable participant.

The Supervisor therefore rejects these zero-work inputs during validation:

- broadcast with an empty `agents` array;
- sequential with an empty `steps` array;
- relay with an empty `steps` array.

The standalone strategy functions may still expose their existing empty-input
behavior for callers that intentionally use them as low-level utilities. The
restriction is specific to the Supervisor execution contract, where a successful
run must represent at least one dispatched unit of work.
