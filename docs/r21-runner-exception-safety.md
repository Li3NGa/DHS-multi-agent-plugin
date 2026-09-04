# R21 — AgentRunner exception-safety contract

`AgentRunner.run()` is a non-throwing task execution boundary for expected runtime
failures. A synchronous exception from DSH `followup()` is converted into a
`TaskOutcome` with `status: 'failed'` and the normalized error message.

Cancellation is best-effort. If the host invokes `agent.cancel()` for a timeout or
an `AbortSignal` and that cancel call itself throws, the exception is contained and
the runner continues through its normal timeout/cancellation outcome path.

This prevents provider/harness implementation exceptions from escaping asynchronous
handlers and leaving the caller with a permanently unsettled task promise.
