"""Dependency-aware task scheduler with cooperative cancellation.

Executes a TaskPlan on the shared bounded executor. Tasks whose
dependencies have all succeeded are launched as soon as a worker slot is
free (event-driven, not wave-synchronized); a dependency that fails,
times out or is cancelled cascades SKIPPED to all of its dependents.

``run_task(task) -> Any`` performs the actual work. Its return value is
interpreted as:

- a TaskResult -> used verbatim
- a dict containing "error" -> FAILED with that error (the convention
  used by the agent-call helpers); the literal ``{"error": "timeout"}``
  marks the task TIMEOUT
- anything else -> SUCCESS with the value as output

Exceptions raised by ``run_task`` mark the task FAILED, except
BudgetExceeded which aborts the whole plan: remaining tasks are marked
CANCELLED and the exception propagates so the run stops spending.

An absolute ``deadline`` (monotonic seconds) caps the whole plan: once it
passes, no new task is launched and RunTimeout aborts the plan (running
tasks are cancelled); work that already finished keeps its result.

Three distinct time limits (P0 fix — they were previously conflated):

- **task deadline**: per-task execution limit derived from
  ``Task.timeout`` / ``default_timeout``, clamped to the remaining run
  budget. Carried into the task as ``TaskContext.deadline``.
- **run deadline**: the absolute cutoff for the whole ``execute`` call
  (the ``deadline=`` argument, falling back to the ``run_deadline()``
  contextvar).
- **provider timeout**: per-LLM/HTTP-call timeout, applied by
  ``clamp_timeout`` in the agent dispatch layer, not here.

Cooperative cancellation (P0 fix):

- ``future.cancel()`` can only cancel a future that has **not started**;
  it can NEVER kill an already-running Python thread. It is used here
  only as an auxiliary measure for not-yet-started work.
- Running tasks are asked to stop through a :class:`CancellationToken`
  (run-level token parented to every task token). A well-behaved task
  polls ``TaskContext.cancellation`` and exits on its own; a blocking
  task is ultimately released by its provider / HTTP timeout.

When the run deadline passes the scheduler (in order): stops launching
new tasks; requests cancellation of every running task; marks pending
tasks CANCELLED; marks still-running tasks CANCELLED (their threads are
left to end via cooperative checks / provider timeouts); and exits —
``execute`` raises ``RunTimeout`` (backwards-compatible), while
``execute_run`` returns a :class:`RunResult` with ``status == "timeout"``.
The scheduler never waits indefinitely, so it can never loop forever.
"""
import inspect
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from ..context import CancellationToken, CancelledError, TaskContext
from ..exceptions import BudgetExceeded, PoolSaturated, RunTimeout, TaskError
from .deadline import run_deadline
from .executor import shared_executor
from .task import Task, TaskPlan, TaskResult, TaskStatus

_UNSUCCESSFUL = frozenset({
    TaskStatus.FAILED,
    TaskStatus.TIMEOUT,
    TaskStatus.CANCELLED,
    TaskStatus.SKIPPED,
})


@dataclass
class RunResult:
    """Outcome of a whole scheduler run (see :meth:`TaskScheduler.execute_run`).

    ``status`` is one of ``"success"``, ``"failed"`` (at least one task
    failed or timed out), ``"timeout"`` (run deadline exceeded) or
    ``"cancelled"`` (budget exhausted / run aborted). ``results`` always
    contains a terminal TaskResult for every task in the plan — no task
    is left dangling, even on abort.
    """

    status: str
    results: Dict[str, TaskResult] = field(default_factory=dict)
    reason: Optional[str] = None

    @property
    def timed_out(self) -> bool:
        return self.status == "timeout"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "results": {tid: r.as_dict() for tid, r in self.results.items()},
        }


def _accepts_context(fn: Callable) -> bool:
    """Best-effort check whether ``run_task`` takes a ``TaskContext`` second arg.

    Legacy one-argument callables keep working unchanged; callables that
    accept a second positional argument (or ``*args``) receive the
    :class:`TaskContext` (task_id / cancellation / deadline).
    """
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):  # builtins / C callables without introspection
        return False
    positional = 0
    for param in sig.parameters.values():
        if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
            positional += 1
        elif param.kind == inspect.Parameter.VAR_POSITIONAL:
            return True
    return positional >= 2


class _Running:
    __slots__ = ("task", "deadline", "started", "token")

    def __init__(self, task: Task, deadline: Optional[float], token: CancellationToken):
        self.task = task
        self.deadline = deadline
        self.started = time.monotonic()
        self.token = token


class TaskScheduler:
    """Run a TaskPlan as a DAG on the shared bounded executor."""

    def __init__(
        self,
        run_task: Callable,
        max_concurrency: Optional[int] = None,
        default_timeout: Optional[float] = None,
        executor: Optional[ThreadPoolExecutor] = None,
        deadline: Optional[float] = None,
    ):
        self._run_task = run_task
        self._max_concurrency = max_concurrency
        self._default_timeout = default_timeout
        self._executor = executor if executor is not None else shared_executor()
        self._deadline = deadline
        self._run_task_takes_context = _accepts_context(run_task)
        self._last_results: Dict[str, TaskResult] = {}

    # -- public API ---------------------------------------------------------
    def execute(
        self,
        plan: TaskPlan,
        on_event: Optional[Callable[[Task, TaskResult], None]] = None,
    ) -> Dict[str, TaskResult]:
        """Run the plan; returns ``{task_id: TaskResult}`` (legacy API).

        Raises ``RunTimeout`` when the run deadline is exceeded and
        propagates ``BudgetExceeded`` / ``TaskError`` as before.
        """
        return self._run(plan, on_event)

    def execute_run(
        self,
        plan: TaskPlan,
        on_event: Optional[Callable[[Task, TaskResult], None]] = None,
    ) -> RunResult:
        """Run the plan and return a structured :class:`RunResult`.

        Unlike :meth:`execute` this never raises for run-level outcomes:
        a run deadline breach is reported as ``status == "timeout"``
        (requirement: the final RunResult must explicitly say TIMEOUT).
        """
        try:
            results = self._run(plan, on_event)
        except RunTimeout as exc:
            return RunResult("timeout", dict(self._last_results), str(exc))
        except BudgetExceeded as exc:
            return RunResult("cancelled", dict(self._last_results), str(exc))
        except TaskError as exc:
            return RunResult("failed", dict(self._last_results), str(exc))
        failed = any(
            r.status in (TaskStatus.FAILED, TaskStatus.TIMEOUT) for r in results.values()
        )
        return RunResult("failed" if failed else "success", dict(results), None)

    # -- internals ----------------------------------------------------------
    def _run(
        self,
        plan: TaskPlan,
        on_event: Optional[Callable[[Task, TaskResult], None]] = None,
    ) -> Dict[str, TaskResult]:
        plan.validate()
        # run deadline: explicit argument wins, else the active contextvar.
        deadline = self._deadline if self._deadline is not None else run_deadline()
        # run-level token; every task token is a child of it, so cancelling
        # it requests cancellation of *all* tasks at once.
        run_token = CancellationToken()
        results: Dict[str, TaskResult] = {}
        pending: Dict[str, Task] = {t.id: t for t in plan.tasks}
        running: Dict[Future, _Running] = {}
        self._last_results = {}
        try:
            while pending or running:
                self._skip_blocked(pending, results, on_event)
                self._launch_ready(pending, running, results, deadline, run_token, on_event)
                if not running:
                    if pending:
                        raise TaskError("scheduler deadlock: unresolvable tasks remain")
                    break
                self._wait(running, results, on_event, deadline)
            # Every task drained; the run deadline may still have been what
            # ended the last tasks (their task deadlines are clamped to it).
            if deadline is not None and time.monotonic() >= deadline:
                if any(r.status is TaskStatus.TIMEOUT for r in results.values()):
                    run_token.cancel("run deadline exceeded")
                    raise RunTimeout("run deadline exceeded")
        except BaseException:
            self._abort(pending, running, results, on_event, run_token)
            self._last_results = results
            raise
        self._last_results = results
        return results

    def _skip_blocked(
        self,
        pending: Dict[str, Task],
        results: Dict[str, TaskResult],
        on_event: Optional[Callable[[Task, TaskResult], None]],
    ) -> None:
        for task_id in list(pending):
            task = pending[task_id]
            for dep in task.depends_on:
                dep_result = results.get(dep)
                if dep_result is not None and dep_result.status in _UNSUCCESSFUL:
                    result = TaskResult(
                        task_id=task_id,
                        status=TaskStatus.SKIPPED,
                        agent=task.agent,
                        error=f"dependency '{dep}' {dep_result.status.value}",
                    )
                    self._finish(task, result, results, on_event)
                    del pending[task_id]
                    break

    def _launch_ready(
        self,
        pending: Dict[str, Task],
        running: Dict[Future, _Running],
        results: Dict[str, TaskResult],
        deadline: Optional[float],
        run_token: CancellationToken,
        on_event: Optional[Callable[[Task, TaskResult], None]] = None,
    ) -> None:
        now = time.monotonic()
        if deadline is not None and now >= deadline:
            # Run deadline reached: stop launching, request cooperative
            # cancellation of everything still running, abort the run.
            run_token.cancel("run deadline exceeded")
            raise RunTimeout("run deadline exceeded")
        for task_id in list(pending):
            if self._max_concurrency is not None and len(running) >= self._max_concurrency:
                return
            task = pending[task_id]
            if not all(
                dep in results and results[dep].status is TaskStatus.SUCCESS
                for dep in task.depends_on
            ):
                continue
            timeout = task.timeout if task.timeout is not None else self._default_timeout
            task_deadline = self._task_deadline(now, timeout, deadline)
            token = CancellationToken(parent=run_token)
            context = TaskContext(task_id=task.id, cancellation=token, deadline=task_deadline)
            task.status = TaskStatus.RUNNING
            try:
                future = self._executor.submit(self._invoke_run_task, task, context)
            except PoolSaturated:
                # every worker is busy; do not park the task in the queue
                # behind them. Finish it as TIMEOUT and try the next one.
                result = TaskResult(
                    task_id=task.id,
                    status=TaskStatus.TIMEOUT,
                    agent=task.agent,
                    error="shared pool saturated",
                )
                self._finish(task, result, results, on_event)
                del pending[task_id]
                continue
            running[future] = _Running(task, task_deadline, token)
            del pending[task_id]

    @staticmethod
    def _task_deadline(now: float, timeout: Optional[float], run_dl: Optional[float]) -> Optional[float]:
        """Task deadline = min(own timeout, remaining run budget).

        Distinguishes the *task deadline* from the *run deadline*: a task
        never outlives the run budget, but its own (shorter) timeout still
        wins when present. Provider timeouts are applied further down in
        the agent dispatch layer via ``clamp_timeout``.
        """
        if timeout is not None:
            own = now + float(timeout)
            return min(own, run_dl) if run_dl is not None else own
        return run_dl  # bounded by the run deadline only (or unbounded)

    def _invoke_run_task(self, task: Task, context: TaskContext) -> Any:
        if self._run_task_takes_context:
            return self._run_task(task, context)
        return self._run_task(task)

    def _wait(
        self,
        running: Dict[Future, _Running],
        results: Dict[str, TaskResult],
        on_event: Optional[Callable[[Task, TaskResult], None]],
        deadline: Optional[float],
    ) -> None:
        timeout = self._nearest_deadline(running, deadline)
        done, _ = wait(running, timeout=timeout, return_when=FIRST_COMPLETED)
        for future in done:
            self._collect(future, running, results, on_event)
        if not done:
            self._expire(running, results, on_event)

    def _nearest_deadline(self, running: Dict[Future, _Running], deadline: Optional[float]) -> Optional[float]:
        deadlines = [r.deadline for r in running.values() if r.deadline is not None]
        if deadline is not None:
            deadlines.append(deadline)
        if not deadlines:
            return None
        remaining = min(deadlines) - time.monotonic()
        return max(0.0, remaining)

    def _expire(
        self,
        running: Dict[Future, _Running],
        results: Dict[str, TaskResult],
        on_event: Optional[Callable[[Task, TaskResult], None]],
    ) -> None:
        now = time.monotonic()
        for future, state in list(running.items()):
            if state.deadline is not None and now >= state.deadline:
                # Cooperative cancellation request: the worker thread
                # observes its token and exits at its next checkpoint.
                state.token.cancel("task deadline exceeded")
                # Auxiliary only — this is a no-op if the worker already
                # picked the task up; it never kills a running thread.
                future.cancel()
                result = TaskResult(
                    task_id=state.task.id,
                    status=TaskStatus.TIMEOUT,
                    agent=state.task.agent,
                    error="task deadline exceeded",
                    duration_ms=(now - state.started) * 1000.0,
                )
                self._finish(state.task, result, results, on_event)
                del running[future]

    def _collect(
        self,
        future: Future,
        running: Dict[Future, _Running],
        results: Dict[str, TaskResult],
        on_event: Optional[Callable[[Task, TaskResult], None]],
    ) -> None:
        state = running.pop(future)
        elapsed = (time.monotonic() - state.started) * 1000.0
        try:
            output = future.result()
        except CancelledError as exc:
            # the task observed its cancellation token and exited early
            result = TaskResult(
                task_id=state.task.id,
                status=TaskStatus.CANCELLED,
                agent=state.task.agent,
                error=exc.reason,
                duration_ms=elapsed,
            )
        except BudgetExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - task failures are results, not aborts
            result = TaskResult(
                task_id=state.task.id,
                status=TaskStatus.FAILED,
                agent=state.task.agent,
                error=str(exc),
                duration_ms=elapsed,
            )
        else:
            result = self._result_from_output(state.task, output, elapsed)
        self._finish(state.task, result, results, on_event)

    @staticmethod
    def _result_from_output(task: Task, output: Any, elapsed: float) -> TaskResult:
        if isinstance(output, TaskResult):
            return output
        if isinstance(output, dict) and "error" in output:
            status = TaskStatus.TIMEOUT if output.get("error") == "timeout" else TaskStatus.FAILED
            return TaskResult(
                task_id=task.id,
                status=status,
                agent=task.agent,
                error=str(output["error"]),
                duration_ms=elapsed,
            )
        return TaskResult(
            task_id=task.id,
            status=TaskStatus.SUCCESS,
            output=output,
            agent=task.agent,
            duration_ms=elapsed,
        )

    def _abort(
        self,
        pending: Dict[str, Task],
        running: Dict[Future, _Running],
        results: Dict[str, TaskResult],
        on_event: Optional[Callable[[Task, TaskResult], None]],
        run_token: CancellationToken,
    ) -> None:
        # Request cooperative cancellation of every still-running task
        # (children of run_token see the request immediately).
        run_token.cancel("run aborted")
        for future in running:
            # Auxiliary only: drops futures that never started. It cannot
            # and does not kill any running thread — those must observe
            # their cancellation token or end on their provider timeout.
            future.cancel()
        for state in running.values():
            self._finish(
                state.task,
                TaskResult(
                    task_id=state.task.id,
                    status=TaskStatus.CANCELLED,
                    agent=state.task.agent,
                    error="cancelled",
                ),
                results,
                on_event,
            )
        for task in pending.values():
            self._finish(
                task,
                TaskResult(
                    task_id=task.id,
                    status=TaskStatus.CANCELLED,
                    agent=task.agent,
                    error="cancelled",
                ),
                results,
                on_event,
            )

    def _finish(
        self,
        task: Task,
        result: TaskResult,
        results: Dict[str, TaskResult],
        on_event: Optional[Callable[[Task, TaskResult], None]],
    ) -> None:
        task.status = result.status
        results[result.task_id] = result
        if on_event is not None:
            on_event(task, result)
