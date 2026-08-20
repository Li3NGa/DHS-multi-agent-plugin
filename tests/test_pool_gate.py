"""Shared pool counting gate.

A saturated pool (every worker busy with a slow call) must fail new
submissions fast instead of parking them in an unbounded queue behind the
slow workers. These tests force a 1-worker pool, occupy its only slot, and
assert that strategies and the scheduler degrade to timeout/error results.
"""
import threading
import time

import pytest

from deepseek_multi_agent_plugin import Agent, AgentCoordinator
from deepseek_multi_agent_plugin.exceptions import PoolSaturated
from deepseek_multi_agent_plugin.runtime.executor import shared_executor, shutdown_executor
from deepseek_multi_agent_plugin.runtime.scheduler import TaskScheduler
from deepseek_multi_agent_plugin.runtime.task import Task, TaskPlan, TaskStatus


@pytest.fixture(autouse=True)
def _reset_pool():
    shutdown_executor(wait=False)
    yield
    shutdown_executor(wait=False)


def _saturate(monkeypatch):
    """Force a 1-worker pool and occupy its only slot; return a releaser."""
    monkeypatch.setenv("DSMA_MAX_CONCURRENCY", "1")
    monkeypatch.setenv("DSMA_POOL_SLOT_TIMEOUT", "0.05")
    pool = shared_executor()
    gate = threading.Event()

    def block():
        gate.wait(5)

    fut = pool.submit(block)

    def release():
        gate.set()
        fut.result(timeout=5)

    return release


def test_submit_fails_fast_when_pool_saturated(monkeypatch):
    release = _saturate(monkeypatch)
    try:
        with pytest.raises(PoolSaturated):
            shared_executor().submit(lambda: None)
    finally:
        release()


def test_sequential_call_degrades_to_timeout(monkeypatch):
    release = _saturate(monkeypatch)
    coord = AgentCoordinator(timeout=1.0)
    coord.register_agent(Agent("a", lambda msg: "ok"))
    try:
        start = time.monotonic()
        result = coord.run("hello", strategy="sequential")
        elapsed = time.monotonic() - start
        assert elapsed < 0.8  # failed fast, did not wait on the occupied slot
        assert result["rounds"][0]["response"] == {"error": "timeout"}
    finally:
        release()


def test_broadcast_degrades_all_to_timeout(monkeypatch):
    release = _saturate(monkeypatch)
    coord = AgentCoordinator(timeout=1.0)
    coord.register_agent(Agent("a", lambda msg: "ok"))
    coord.register_agent(Agent("b", lambda msg: "ok"))
    try:
        start = time.monotonic()
        result = coord.run("hello", strategy="broadcast")
        elapsed = time.monotonic() - start
        assert elapsed < 0.8
        responses = result["rounds"][0]["responses"]
        assert set(responses) == {"a", "b"}
        assert all(r == {"error": "timeout"} for r in responses.values())
    finally:
        release()


def test_scheduler_times_out_task_on_saturation(monkeypatch):
    release = _saturate(monkeypatch)
    plan = TaskPlan(tasks=[Task(id="a", description="x", agent="x")])
    try:
        results = TaskScheduler(lambda t: "done").execute(plan)
        assert results["a"].status is TaskStatus.TIMEOUT
        assert "saturated" in results["a"].error
    finally:
        release()
