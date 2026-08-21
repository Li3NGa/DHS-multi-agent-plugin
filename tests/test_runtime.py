"""Task model, dependency graph and DAG scheduler tests."""
import threading
import time

import pytest

from deepseek_multi_agent_plugin.exceptions import BudgetExceeded, PlanError, RunTimeout
from deepseek_multi_agent_plugin.runtime import (
    CancellationToken,
    RunResult,
    Task,
    TaskContext,
    TaskPlan,
    TaskResult,
    TaskScheduler,
    TaskStatus,
    topological_order,
)


# ---------------------------------------------------------------- model
def test_task_plan_rejects_duplicate_ids():
    tasks = [Task(id="a", description="x"), Task(id="a", description="y")]
    with pytest.raises(PlanError):
        TaskPlan(tasks)


def test_task_plan_rejects_unknown_dependency():
    tasks = [Task(id="a", description="x", depends_on=["ghost"])]
    with pytest.raises(PlanError):
        TaskPlan(tasks)


def test_task_plan_rejects_cycle():
    tasks = [
        Task(id="a", description="x", depends_on=["b"]),
        Task(id="b", description="y", depends_on=["a"]),
    ]
    with pytest.raises(PlanError, match="cycle"):
        TaskPlan(tasks)


def test_task_plan_self_dependency_rejected():
    with pytest.raises(PlanError, match="cycle"):
        TaskPlan([Task(id="a", description="x", depends_on=["a"])])


def test_topological_order_linear():
    order = topological_order(
        ["a", "b", "c"], {"a": [], "b": ["a"], "c": ["b"]}
    )
    assert order == ["a", "b", "c"]


def test_task_status_terminal():
    assert TaskStatus.SUCCESS.is_terminal
    assert TaskStatus.SKIPPED.is_terminal
    assert not TaskStatus.PENDING.is_terminal
    assert not TaskStatus.RUNNING.is_terminal


def test_task_result_dict_shape():
    result = TaskResult(task_id="t", status=TaskStatus.SUCCESS, output="done")
    assert result.as_dict() == {"task_id": "t", "status": "success", "output": "done",
                                "duration_ms": 0.0}


# ---------------------------------------------------------------- scheduler
def _plan(edges, run_task, **kwargs):
    tasks = [Task(id=tid, description=f"task {tid}", depends_on=deps) for tid, deps in edges]
    return TaskPlan(tasks), TaskScheduler(run_task, **kwargs)


def test_diamond_dag_execution_order():
    """A -> B, C -> D: B and C only run after A; D waits for both."""
    events = []
    lock = threading.Lock()

    def run_task(task):
        with lock:
            events.append(("start", task.id))
        time.sleep(0.02)
        with lock:
            events.append(("end", task.id))
        return f"{task.id}-out"

    edges = [("a", []), ("b", ["a"]), ("c", ["a"]), ("d", ["b", "c"])]
    plan, scheduler = _plan(edges, run_task)
    results = scheduler.execute(plan)

    assert {r.status for r in results.values()} == {TaskStatus.SUCCESS}
    assert results["d"].output == "d-out"

    def index(kind, tid):
        return events.index((kind, tid))

    assert index("end", "a") < index("start", "b")
    assert index("end", "a") < index("start", "c")
    assert index("end", "b") < index("start", "d")
    assert index("end", "c") < index("start", "d")


def test_independent_tasks_run_in_parallel():
    started = threading.Barrier(3, timeout=2.0)

    def run_task(task):
        started.wait()  # only passes if all three run concurrently
        return "ok"

    edges = [("a", []), ("b", []), ("c", [])]
    plan, scheduler = _plan(edges, run_task)
    results = scheduler.execute(plan)
    assert len(results) == 3
    assert all(r.status is TaskStatus.SUCCESS for r in results.values())


def test_failed_dependency_skips_dependents():
    def run_task(task):
        if task.id == "a":
            raise RuntimeError("a exploded")
        return "ok"

    edges = [("a", []), ("b", ["a"]), ("c", ["b"]), ("d", [])]
    plan, scheduler = _plan(edges, run_task)
    results = scheduler.execute(plan)

    assert results["a"].status is TaskStatus.FAILED
    assert "a exploded" in results["a"].error
    assert results["b"].status is TaskStatus.SKIPPED
    assert results["c"].status is TaskStatus.SKIPPED
    assert results["d"].status is TaskStatus.SUCCESS


def test_error_dict_result_marks_task_failed():
    def run_task(task):
        return {"error": "timeout"}

    plan, scheduler = _plan([("a", [])], run_task)
    results = scheduler.execute(plan)
    assert results["a"].status is TaskStatus.TIMEOUT
    assert results["a"].error == "timeout"


def test_task_result_passthrough():
    custom = TaskResult(task_id="a", status=TaskStatus.SUCCESS, output="direct")

    plan, scheduler = _plan([("a", [])], lambda task: custom)
    results = scheduler.execute(plan)
    assert results["a"] is custom


def test_per_task_timeout():
    def run_task(task):
        time.sleep(0.5)
        return "late"

    tasks = [Task(id="slow", description="t", timeout=0.05)]
    scheduler = TaskScheduler(run_task)
    start = time.monotonic()
    results = scheduler.execute(TaskPlan(tasks))
    elapsed = time.monotonic() - start

    assert results["slow"].status is TaskStatus.TIMEOUT
    assert elapsed < 0.4


def test_budget_exceeded_cancels_remaining_tasks():
    def run_task(task):
        if task.id == "a":
            raise BudgetExceeded("max_tokens reached")
        return "ok"

    edges = [("a", []), ("b", []), ("c", ["b"])]
    plan, scheduler = _plan(edges, run_task)
    with pytest.raises(BudgetExceeded):
        scheduler.execute(plan)


def test_scheduler_emits_events():
    seen = []

    def on_event(task, result):
        seen.append((task.id, result.status))

    plan, scheduler = _plan([("a", []), ("b", ["a"])], lambda task: "ok")
    scheduler.execute(plan, on_event=on_event)
    assert seen == [("a", TaskStatus.SUCCESS), ("b", TaskStatus.SUCCESS)]


def test_max_concurrency_bounds_inflight_tasks():
    inflight = []
    peak = []
    lock = threading.Lock()

    def run_task(task):
        with lock:
            inflight.append(task.id)
            peak.append(len(inflight))
        time.sleep(0.02)
        with lock:
            inflight.remove(task.id)
        return "ok"

    edges = [(f"t{i}", []) for i in range(6)]
    plan, scheduler = _plan(edges, run_task, max_concurrency=2)
    results = scheduler.execute(plan)
    assert len(results) == 6
    assert max(peak) <= 2


def test_empty_plan_executes_to_empty_results():
    scheduler = TaskScheduler(lambda task: "ok")
    assert scheduler.execute(TaskPlan([])) == {}


# ------------------------------------------------- P0: timeouts & cancellation
def test_cancellation_token_parent_chain():
    """Run-level token cancels all children; a child cancel stays local."""
    parent = CancellationToken()
    child = CancellationToken(parent=parent)
    assert not child.is_cancelled()
    parent.cancel("run deadline exceeded")
    assert child.is_cancelled()
    assert child.reason() == "run deadline exceeded"

    parent2 = CancellationToken()
    child2 = CancellationToken(parent=parent2)
    child2.cancel("task deadline exceeded")
    assert child2.is_cancelled()
    assert not parent2.is_cancelled()  # task-local cancel never leaks upward


def test_task_context_fields():
    token = CancellationToken()
    ctx = TaskContext(task_id="t", cancellation=token, deadline=time.monotonic() + 1.0)
    assert ctx.task_id == "t"
    assert ctx.cancellation is token
    assert ctx.deadline is not None and ctx.deadline > time.monotonic()
    assert 0.0 < ctx.remaining() <= 1.0
    assert not ctx.is_expired()


def test_run_task_context_injection():
    """Two-arg run_task receives TaskContext (task_id / cancellation / deadline)."""
    box = {}

    def run_task(task, ctx):
        box["task_id"] = ctx.task_id
        box["cancellation"] = ctx.cancellation
        box["deadline"] = ctx.deadline
        return "ok"

    scheduler = TaskScheduler(run_task, default_timeout=5.0)
    results = scheduler.execute(TaskPlan([Task(id="x1", description="d")]))
    assert results["x1"].status is TaskStatus.SUCCESS
    assert box["task_id"] == "x1"
    assert box["cancellation"] is not None and not box["cancellation"].is_cancelled()
    assert box["deadline"] is not None  # task deadline derived from default_timeout


def test_task_timeout():
    """Task deadline (Task.timeout) expiry marks TIMEOUT and requests cancel."""
    seen = {}

    def run_task(task, ctx):
        seen["token"] = ctx.cancellation
        for _ in range(100):
            if ctx.cancellation.is_cancelled():
                return "stopped-early"
            time.sleep(0.01)
        return "late"

    tasks = [Task(id="slow", description="t", timeout=0.05)]
    scheduler = TaskScheduler(run_task)
    start = time.monotonic()
    results = scheduler.execute(TaskPlan(tasks))
    elapsed = time.monotonic() - start

    assert results["slow"].status is TaskStatus.TIMEOUT
    assert elapsed < 1.0
    # the scheduler delivered a cooperative cancellation request even
    # though the worker thread itself cannot be killed
    assert seen["token"].is_cancelled()


def test_run_timeout():
    """Run deadline expiry is reported explicitly by execute_run()."""
    def run_task(task):
        time.sleep(0.5)
        return "late"

    plan = TaskPlan([Task(id="a", description="x"), Task(id="b", description="y")])
    scheduler = TaskScheduler(run_task, deadline=time.monotonic() + 0.1)
    run = scheduler.execute_run(plan)

    assert isinstance(run, RunResult)
    assert run.status == "timeout"
    assert run.timed_out is True
    assert set(run.results) == {"a", "b"}
    # every task ends in a terminal state — none is left dangling
    assert all(
        r.status in (TaskStatus.TIMEOUT, TaskStatus.CANCELLED)
        for r in run.results.values()
    )


def test_task_cancellation():
    """A running task observes its CancellationToken and exits cooperatively."""
    exited = threading.Event()

    def run_task(task, ctx):
        for _ in range(500):
            if ctx.cancellation.is_cancelled():
                exited.set()
                return "stopped"
            time.sleep(0.01)
        return "late"

    tasks = [Task(id="c1", description="t", timeout=0.08)]
    scheduler = TaskScheduler(run_task)
    results = scheduler.execute(TaskPlan(tasks))

    assert results["c1"].status is TaskStatus.TIMEOUT
    # the thread really exited via cooperation (not killed, asked + obeyed)
    assert exited.wait(timeout=2.0)


def test_run_cancellation():
    """Run deadline requests cancellation of all running tasks."""
    seen_tokens = []
    lock = threading.Lock()

    def run_task(task, ctx):
        with lock:
            seen_tokens.append(ctx.cancellation)
        for _ in range(500):
            if ctx.cancellation.is_cancelled():
                return "stopped"
            time.sleep(0.01)
        return "late"

    plan = TaskPlan([Task(id=f"t{i}", description="x") for i in range(3)])
    scheduler = TaskScheduler(run_task, deadline=time.monotonic() + 0.12)
    run = scheduler.execute_run(plan)

    assert run.status == "timeout"
    assert len(seen_tokens) == 3
    # every running task's token carries the run-level cancel request
    assert all(t.is_cancelled() for t in seen_tokens)


def test_pending_tasks_cancelled():
    """Tasks never started when the run deadline hits are CANCELLED."""
    def run_task(task):
        time.sleep(0.3)
        return "late"

    plan = TaskPlan([
        Task(id="first", description="x"),
        Task(id="second", description="y"),
        Task(id="third", description="z"),
    ])
    scheduler = TaskScheduler(run_task, max_concurrency=1, deadline=time.monotonic() + 0.1)
    run = scheduler.execute_run(plan)

    assert run.status == "timeout"
    assert run.results["first"].status is TaskStatus.TIMEOUT
    assert run.results["second"].status is TaskStatus.CANCELLED
    assert run.results["third"].status is TaskStatus.CANCELLED


def test_running_tasks_cancel_requested():
    """On run deadline every *running* task receives a cancellation request."""
    token_box = {}

    def run_task(task, ctx):
        token_box[task.id] = ctx.cancellation
        time.sleep(0.5)  # deliberately ignores the token (worst case)
        return "late"

    plan = TaskPlan([Task(id="r1", description="x"), Task(id="r2", description="y")])
    scheduler = TaskScheduler(run_task, max_concurrency=1, deadline=time.monotonic() + 0.1)
    run = scheduler.execute_run(plan)

    assert run.status == "timeout"
    assert "r1" in token_box  # r1 really was running
    assert token_box["r1"].is_cancelled()  # and got the cancel request
    assert run.results["r2"].status is TaskStatus.CANCELLED  # never started


def test_deadline_does_not_loop_forever():
    """THE regression test: a task sleeps far past the run deadline; the
    scheduler must still return promptly (no infinite loop, no unbounded join)."""
    def run_task(task):
        time.sleep(2.5)
        return "late"

    plan = TaskPlan([Task(id="sleepy", description="x")])
    scheduler = TaskScheduler(run_task, deadline=time.monotonic() + 0.15)
    start = time.monotonic()
    run = scheduler.execute_run(plan)
    elapsed = time.monotonic() - start

    assert run.status == "timeout"
    assert run.results["sleepy"].status in (TaskStatus.TIMEOUT, TaskStatus.CANCELLED)
    assert elapsed < 1.5  # bounded — far below the task's own 2.5s sleep


def test_execute_still_raises_run_timeout():
    """Legacy execute() keeps raising RunTimeout on run deadline breach."""
    plan = TaskPlan([Task(id="a", description="x"), Task(id="b", description="y")])
    scheduler = TaskScheduler(lambda task: (time.sleep(0.3), "late")[1],
                              deadline=time.monotonic() + 0.1)
    with pytest.raises(RunTimeout):
        scheduler.execute(plan)


def test_dependency_blocked_after_failure():
    """Dependents of a failed task end SKIPPED; independent siblings still run."""
    def run_task(task):
        if task.id == "a":
            raise RuntimeError("boom")
        return f"{task.id}-ok"

    plan = TaskPlan([
        Task(id="a", description="x"),
        Task(id="b", description="y", depends_on=["a"]),
        Task(id="c", description="z", depends_on=["b"]),
        Task(id="d", description="w"),
    ])
    scheduler = TaskScheduler(run_task)
    run = scheduler.execute_run(plan)

    assert run.status == "failed"
    assert run.results["a"].status is TaskStatus.FAILED
    assert run.results["b"].status is TaskStatus.SKIPPED
    assert run.results["c"].status is TaskStatus.SKIPPED
    assert run.results["d"].status is TaskStatus.SUCCESS


def test_concurrency_limit_preserved():
    """max_concurrency stays a hard ceiling with the new cancellation path."""
    inflight = []
    peak = []
    lock = threading.Lock()

    def run_task(task):
        with lock:
            inflight.append(task.id)
            peak.append(len(inflight))
        time.sleep(0.02)
        with lock:
            inflight.remove(task.id)
        return "ok"

    edges = [(f"t{i}", []) for i in range(6)]
    plan, scheduler = _plan(edges, run_task, max_concurrency=2)
    run = scheduler.execute_run(plan)
    assert len(run.results) == 6
    assert all(r.status is TaskStatus.SUCCESS for r in run.results.values())
    assert max(peak) <= 2


def test_run_result_dict_shape():
    run = RunResult("timeout", {}, "run deadline exceeded")
    assert run.as_dict() == {"status": "timeout", "reason": "run deadline exceeded", "results": {}}
