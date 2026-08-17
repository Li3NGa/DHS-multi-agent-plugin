# -*- coding: utf-8 -*-
"""Task / Trace / Agent 可观测性测试。"""
import json
import threading

import pytest

from deepseek_multi_agent_plugin import AgentCoordinator, RunRegistry
from deepseek_multi_agent_plugin.adapter_server import build_server, register_demo_agents
from deepseek_multi_agent_plugin.agents import AgentFactory
from deepseek_multi_agent_plugin.observability import (
    Trace,
    agent_health,
    current_trace,
)


def _coord():
    coord = AgentCoordinator()
    register_demo_agents(coord)
    return coord


def test_run_returns_run_id_and_records_trace():
    coord = _coord()
    result = coord.run("hello", strategy="broadcast", rounds=1)
    run_id = result["meta"]["run_id"]
    assert isinstance(run_id, str) and len(run_id) == 12
    trace = coord.runs.get(run_id)
    assert trace is not None
    assert trace.status == "ok"
    # broadcast 一轮：alpha + beta 各产生一个 span
    assert len(trace.spans) == 2
    assert {s.agent for s in trace.spans} == {"alpha", "beta"}
    assert all(s.status == "ok" for s in trace.spans)
    assert trace.tasks and trace.tasks[0].name == "round 1"


def test_sequential_trace_counts_every_step():
    coord = _coord()
    result = coord.run("hello", strategy="sequential")
    trace = coord.runs.get(result["meta"]["run_id"])
    assert len(trace.spans) == 2
    assert [t.name for t in trace.tasks] == ["1", "2"]


def test_error_span_status():
    coord = AgentCoordinator()
    coord.register_agent(AgentFactory.create_agent("mock", "ok"))
    coord.register_agent(AgentFactory.create_agent("custom", "boom", handler=_boom))
    result = coord.run("hello", strategy="broadcast", rounds=1)
    trace = coord.runs.get(result["meta"]["run_id"])
    by_agent = {s.agent: s for s in trace.spans}
    assert by_agent["ok"].status == "ok"
    assert by_agent["boom"].status == "error"
    assert by_agent["boom"].error


def _boom(message, context=None):  # custom handler that always fails
    raise RuntimeError("boom")


def test_failed_run_records_error_trace():
    coord = _coord()
    with pytest.raises(ValueError):
        coord.run("hello", strategy="nope")
    summary = coord.runs.recent(1)[0]
    assert summary["status"] == "error"
    assert "Unknown strategy" in summary["error"]


def test_agent_health_counters():
    coord = _coord()
    coord.run("hello", strategy="broadcast", rounds=1)
    for agent in coord.agents:
        snap = agent_health(agent)
        assert snap["calls"] == 1
        assert snap["ok"] == 1
        assert snap["errors"] == 0
        assert snap["avg_ms"] >= 0


def test_registry_bounds_and_lookup():
    registry = RunRegistry(limit=3)
    traces = []
    for i in range(5):
        trace = Trace(prompt=f"p{i}", strategy="broadcast")
        trace.finish()
        registry.record(trace)
        traces.append(trace)
    assert len(registry) == 3
    assert registry.get(traces[0].run_id) is None  # 已被淘汰
    assert registry.get(traces[4].run_id) is traces[4]
    summaries = registry.recent(10)
    assert [s["prompt"] for s in summaries] == ["p4", "p3", "p2"]


def test_trace_recorded_once():
    trace = Trace(prompt="p", strategy="broadcast")
    trace.finish()
    registry = RunRegistry()
    registry.record(trace)
    registry.record(trace)
    assert len(registry) == 1


def test_no_trace_leak_between_runs():
    coord = _coord()
    coord.run("one", strategy="broadcast", rounds=1)
    assert current_trace() is None
    coord.run("two", strategy="broadcast", rounds=1)
    assert len(coord.runs) == 2


def test_concurrent_runs_do_not_share_trace():
    coord = _coord()
    seen_traces = []

    def worker():
        result = coord.run("hi", strategy="broadcast", rounds=1)
        seen_traces.append(coord.runs.get(result["meta"]["run_id"]))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(coord.runs) == 4
    run_ids = {t.run_id for t in seen_traces}
    assert len(run_ids) == 4
    # 每次 run 的 span 都归属正确的 trace（各 2 个）
    for trace in seen_traces:
        assert {s.agent for s in trace.spans} == {"alpha", "beta"}


def test_history_records_run_id(tmp_path):
    from deepseek_multi_agent_plugin.coordinator import DeepseekAdapter
    from deepseek_multi_agent_plugin.history import RunHistory

    coord = _coord()
    history = RunHistory(str(tmp_path / "history.jsonl"))
    adapter = DeepseekAdapter(coord, history=history)
    result = adapter.handle_harness_event(
        {"type": "run", "prompt": "hello", "strategy": "broadcast", "rounds": 1})
    records = history.recent(1)
    assert records[0]["run_id"] == result["meta"]["run_id"]


def test_http_status_runs_and_trace_endpoints():
    coord = _coord()
    server = build_server("127.0.0.1", 0, coord)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_port
        from urllib import request as urlreq

        with urlreq.urlopen(f"http://127.0.0.1:{port}/status", timeout=10) as resp:
            status = json.loads(resp.read().decode())
        assert status["status"] == "ok"
        assert status["version"]
        assert {a["name"] for a in status["agents"]} == {"alpha", "beta"}

        body = json.dumps({"type": "run", "prompt": "hi",
                           "strategy": "broadcast", "rounds": 1}).encode()
        req = urlreq.Request(f"http://127.0.0.1:{port}/run", data=body,
                             headers={"Content-Type": "application/json"})
        with urlreq.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
        run_id = result["meta"]["run_id"]

        with urlreq.urlopen(f"http://127.0.0.1:{port}/runs", timeout=10) as resp:
            runs = json.loads(resp.read().decode())["runs"]
        assert runs[0]["run_id"] == run_id
        assert runs[0]["spans"] == 2

        with urlreq.urlopen(f"http://127.0.0.1:{port}/runs/{run_id}", timeout=10) as resp:
            detail = json.loads(resp.read().decode())
        assert len(detail["span_list"]) == 2
        assert detail["task_list"]

        try:
            urlreq.urlopen(f"http://127.0.0.1:{port}/runs/deadbeef", timeout=10)
            raise AssertionError("expected 404")
        except urlreq.HTTPError as exc:
            assert exc.code == 404
    finally:
        server.shutdown()
        server.server_close()
