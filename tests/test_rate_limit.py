# -*- coding: utf-8 -*-
"""并发 run 限流（DeepseekAdapter._run_gate）与 register 数量上限测试。"""
import threading

from deepseek_multi_agent_plugin.agents import Agent
from deepseek_multi_agent_plugin.coordinator import AgentCoordinator, DeepseekAdapter


def _make_blocking_adapter(max_concurrent_runs=2, run_gate_timeout=0.2):
    coord = AgentCoordinator()
    blocker = _BlockingAgent()
    coord.register_agent(Agent("slow", blocker))
    coord.register_agent(Agent("fast", lambda msg: "ok"))
    adapter = DeepseekAdapter(
        coord,
        max_concurrent_runs=max_concurrent_runs,
        run_gate_timeout=run_gate_timeout,
    )
    return adapter, blocker


class _BlockingAgent:
    """进入后阻塞，直到显式放行（模拟慢 worker）。"""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, msg):
        self.entered.set()
        self.release.wait(timeout=10)
        return "done"


def _run_event(prompt="x"):
    return {"type": "run", "prompt": prompt, "strategy": "sequential",
            "order": ["slow"], "rounds": 1}


def test_runs_beyond_limit_fail_fast():
    adapter, blocker = _make_blocking_adapter(max_concurrent_runs=2)
    results = []

    def run_worker():
        results.append(adapter.handle_harness_event(_run_event()))

    # 前两个 run 各占一个 slot，并阻塞在 slow agent。
    threads = [threading.Thread(target=run_worker) for _ in range(2)]
    for t in threads:
        t.start()
    assert blocker.entered.wait(timeout=5)
    # 第三个 run 在 gate 已满时快速失败，而不是排队等待。
    third = adapter.handle_harness_event(_run_event())
    assert third.get("error") == "too many concurrent runs"
    blocker.release.set()
    for t in threads:
        t.join(timeout=10)

    assert len(results) == 2
    assert all("error" not in r for r in results)


def test_runs_under_limit_all_succeed():
    adapter, blocker = _make_blocking_adapter(max_concurrent_runs=4, run_gate_timeout=5.0)
    results = []

    def run_worker():
        results.append(adapter.handle_harness_event(_run_event()))

    threads = [threading.Thread(target=run_worker) for _ in range(3)]
    for t in threads:
        t.start()
    assert blocker.entered.wait(timeout=5)
    blocker.release.set()
    for t in threads:
        t.join(timeout=10)

    assert len(results) == 3
    assert all("error" not in r for r in results)


def test_gate_is_released_after_run_and_can_be_reused():
    adapter, blocker = _make_blocking_adapter(max_concurrent_runs=1, run_gate_timeout=0.2)

    def run_worker():
        return adapter.handle_harness_event(_run_event())

    # 第一个 run 在后台阻塞，占用唯一的 slot。
    t = threading.Thread(target=run_worker)
    t.start()
    assert blocker.entered.wait(timeout=5)
    second = adapter.handle_harness_event(_run_event())
    assert second.get("error") == "too many concurrent runs"

    # 释放后 gate 恢复：后续 run 不再被限流。
    blocker.release.set()
    t.join(timeout=10)
    third = adapter.handle_harness_event(_run_event())
    assert "error" not in third


def test_register_event_caps_agent_count():
    coord = AgentCoordinator()
    adapter = DeepseekAdapter(coord, max_concurrent_runs=2)
    many = [{"name": f"x{i}", "kind": "echo"} for i in range(adapter.MAX_REGISTER_AGENTS + 1)]
    out = adapter.handle_harness_event({"type": "register", "agents": many})
    assert out["error"] == f"too many agents (max {adapter.MAX_REGISTER_AGENTS})"
    # 未超过上限则正常注册
    out = adapter.handle_harness_event(
        {"type": "register", "agents": [{"name": "ok", "kind": "echo"}]})
    assert out == {"registered": ["ok"]}
