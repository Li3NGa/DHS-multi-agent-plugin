"""Dependency-aware task scheduler.

Executes a TaskPlan on the shared bounded executor. Tasks whose
dependencies have all succeeded are launched as soon as a worker slot is
free (event-driven, not wave-synchronized); a dependency that fails,
times out or is cancelled cascades SKIPPED to all of its dependents.

``run_task(task) -> Any`` performs the actual work. Its return value is
interpreted as:

- a TaskResult -> used verbatim
- a dict containing "error" -> FAILED with that error (the convention
  used by the agent-call helpers)
- anything else -> SUCCESS with the value as output

Exceptions raised by ``run_task`` mark the task FAILED, except
BudgetExceeded which aborts the whole plan: remaining tasks are marked
CANCELLED and the exception propagates so the run stops spending.

An absolute ``deadline`` (monotonic seconds) caps the whole plan: once it
passes, no new task is launched and RunTimeout aborts the plan (running
tasks are cancelled); work that already finished keeps its result.
"""
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any, Callable, Dict, Optional

from ..exceptions import BudgetExceeded, RunTimeout, TaskError
from .executor import shared_executor
from .task import Task, TaskPlan, TaskResult, TaskStatus

_UNSUCCESSFUL = frozenset({
    TaskStatus.FAILED,
    TaskStatus.TIMEOUT,
    TaskStatus.CANCELLED,
    TaskStatus.SKIPPED,
})


class _Running:
    __slots__ = ("task", "deadline", "started")

    def __init__(self, task: Task, deadline: Optional[float]):
        self.task = task
        self.deadline = deadline
        self.started = time.monotonic()


class TaskScheduler:
    """Run a TaskPlan as a DAG on the shared bounded executor."""

    def __init__(
        self,
        run_task: Callable[[Task], Any],
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

    # -- public API ---------------------------------------------------------
    def execute(
        self,
        plan: TaskPlan,
        on_event: Optional[Callable[[Task, TaskResult], None]] = None,
    ) -> Dict[str, TaskResult]:
        plan.validate()
        results: Dict[str, TaskResult] = {}
        pending: Dict[str, Task] = {t.id: t for t in plan.tasks}
        running: Dict[Future, _Running] = {}
        try:
            while pending or running:
                self._skip_blocked(pending, results, on_event)
                self._launch_ready(pending, running, results)
                if not running:
                    if pending:
                        raise TaskError("scheduler deadlock: unresolvable tasks remain")
                    break
                self._wait(running, results, on_event)
        except BaseException:
            self._abort(pending, running, results, on_event)
            raise
        return results

    # -- internals ----------------------------------------------------------
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
    ) -> None:
        if self._deadline is not None and time.monotonic() >= self._deadline:
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
            deadline = time.monotonic() + timeout if timeout is not None else None
            task.status = TaskStatus.RUNNING
            future = self._executor.submit(self._run_task, task)
            running[future] = _Running(task, deadline)
            del pending[task_id]

    def _wait(
        self,
        running: Dict[Future, _Running],
        results: Dict[str, TaskResult],
        on_event: Optional[Callable[[Task, TaskResult], None]],
    ) -> None:
        timeout = self._nearest_deadline(running)
        done, _ = wait(running, timeout=timeout, return_when=FIRST_COMPLETED)
        for future in done:
            self._collect(future, running, results, on_event)
        if not done:
            self._expire(running, results, on_event)

    def _nearest_deadline(self, running: Dict[Future, _Running]) -> Optional[float]:
        deadlines = [r.deadline for r in running.values() if r.deadline is not None]
        if self._deadline is not None:
            deadlines.append(self._deadline)
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
                future.cancel()  # no-op if the worker already picked it up
                result = TaskResult(
                    task_id=state.task.id,
                    status=TaskStatus.TIMEOUT,
                    agent=state.task.agent,
                    error="timeout",
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
    ) -> None:
        for future in running:
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
