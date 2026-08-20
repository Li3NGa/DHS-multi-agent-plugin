"""Task model, dependency graph and DAG scheduler tests."""
import threading
import time

import pytest

from deepseek_multi_agent_plugin.exceptions import BudgetExceeded, PlanError
from deepseek_multi_agent_plugin.runtime import (
    Task,
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
