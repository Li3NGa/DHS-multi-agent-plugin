"""Concurrency behavior: default timeouts, run deadlines, cancellation."""
import json
import time

import pytest

from deepseek_multi_agent_plugin import Agent, AgentCoordinator
from deepseek_multi_agent_plugin.exceptions import RunTimeout
from deepseek_multi_agent_plugin.runtime import (
    Task,
    TaskPlan,
    TaskScheduler,
    clamp_timeout,
    end_run_deadline,
    run_deadline,
    start_run_deadline,
)
from deepseek_multi_agent_plugin.runtime.task import TaskStatus


def _slow_coord(seconds, timeout=None):
    coord = AgentCoordinator(timeout=timeout) if timeout is not None else AgentCoordinator()
    coord.register_agent(Agent("slow", lambda msg: (time.sleep(seconds), "late")[1]))
    coord.register_agent(Agent("fast", lambda msg: "ok"))
    return coord


def test_coordinator_timeout_applies_by_default():
    coord = _slow_coord(1.0, timeout=0.2)
    result = coord.run("hello", strategy="broadcast", rounds=1)
    responses = result["rounds"][0]["responses"]
    assert responses["fast"] == "ok"
    assert responses["slow"] == {"error": "timeout"}


def test_explicit_timeout_overrides_coordinator_default():
    coord = _slow_coord(0.5, timeout=30.0)
    result = coord.run("hello", strategy="broadcast", rounds=1, timeout=0.2)
    assert result["rounds"][0]["responses"]["slow"] == {"error": "timeout"}


def test_run_timeout_aborts_slow_run():
    coord = _slow_coord(5.0, timeout=30.0)
    with pytest.raises(RunTimeout):
        coord.run("hello", strategy="broadcast", rounds=1, run_timeout=0.2)


def test_run_timeout_records_error_trace():
    coord = _slow_coord(5.0, timeout=30.0)
    with pytest.raises(RunTimeout):
        coord.run("hello", strategy="broadcast", rounds=1, run_timeout=0.2)
    latest = coord.runs.recent(1)[0]
    assert latest["status"] == "error"


def test_run_timeout_leaves_no_deadline_behind():
    coord = AgentCoordinator()
    coord.register_agent(Agent("a", lambda msg: (time.sleep(0.3), "late")[1]))
    with pytest.raises(RunTimeout):
        coord.run("hello", run_timeout=0.05, strategy="sequential")
    assert run_deadline() is None
    coord.register_agent(Agent("b", lambda msg: "ok"))
    result = coord.run("again", strategy="sequential", order=["b"])
    assert result["final"] == "ok"


def test_run_timeout_aborts_dag_plan():
    coord = AgentCoordinator()
    plan = json.dumps({"tasks": [
        {"id": "t1", "description": "one", "agent": "w"},
        {"id": "t2", "description": "two", "agent": "w", "depends_on": ["t1"]},
        {"id": "t3", "description": "three", "agent": "w", "depends_on": ["t2"]},
    ]})

    def supervisor(msg):
        return plan if "JSON" in str(msg) else "report"

    def worker(msg):
        time.sleep(0.3)
        return "done"

    coord.register_agent(Agent("supervisor", supervisor))
    coord.register_agent(Agent("w", worker))
    with pytest.raises(RunTimeout):
        coord.run("goal", strategy="supervisor", run_timeout=0.6, timeout=5)


def test_clamp_timeout_without_deadline_is_identity():
    assert clamp_timeout(None) is None
    assert clamp_timeout(1.5) == 1.5


def test_clamp_timeout_bounds_by_remaining_budget():
    token = start_run_deadline(0.3)
    try:
        assert clamp_timeout(5.0) <= 0.3
        assert clamp_timeout(None) <= 0.3
    finally:
        end_run_deadline(token)
    assert run_deadline() is None


def test_clamp_timeout_raises_once_budget_spent():
    token = start_run_deadline(-1.0)
    try:
        with pytest.raises(RunTimeout):
            clamp_timeout(1.0)
    finally:
        end_run_deadline(token)


def test_scheduler_deadline_aborts_plan():
    plan = TaskPlan([
        Task(id="a", description="first"),
        Task(id="b", description="second", depends_on=["a"]),
    ])
    deadline = time.monotonic() + 0.2
    scheduler = TaskScheduler(lambda task: (time.sleep(0.3), "late")[1], deadline=deadline)
    with pytest.raises(RunTimeout):
        scheduler.execute(plan)


def test_scheduler_deadline_preserves_finished_work():
    started = []

    def run(task):
        started.append(task.id)
        if task.id == "b":
            time.sleep(0.3)
        return f"{task.id}-out"

    plan = TaskPlan([
        Task(id="a", description="first"),
        Task(id="b", description="slow"),
    ])
    deadline = time.monotonic() + 0.2
    scheduler = TaskScheduler(run, deadline=deadline)
    with pytest.raises(RunTimeout):
        scheduler.execute(plan)
    assert set(started) == {"a", "b"}


def test_scheduler_deadline_allows_fast_plans():
    plan = TaskPlan([Task(id=f"t{i}", description=str(i)) for i in range(5)])
    scheduler = TaskScheduler(lambda task: "ok", deadline=time.monotonic() + 10)
    results = scheduler.execute(plan)
    assert {r.status for r in results.values()} == {TaskStatus.SUCCESS}
