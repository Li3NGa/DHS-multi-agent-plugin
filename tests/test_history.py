# -*- coding: utf-8 -*-
"""RunHistory 持久化与 history 事件 / HTTP 端点 / MCP 工具的测试。"""
import json
import os
import threading
from urllib import request as urlreq

import pytest

from deepseek_multi_agent_plugin import AgentCoordinator
from deepseek_multi_agent_plugin.adapter_server import build_server, register_demo_agents
from deepseek_multi_agent_plugin.coordinator import DeepseekAdapter
from deepseek_multi_agent_plugin.history import RunHistory
from deepseek_multi_agent_plugin.mcp_server import McpServer


# -- RunHistory 本体 ---------------------------------------------------------
def test_runhistory_append_recent_len_clear(tmp_path):
    h = RunHistory(str(tmp_path / "runs.jsonl"))
    assert len(h) == 0
    h.append({"strategy": "broadcast", "prompt": "p1"})
    h.append({"strategy": "relay", "prompt": "p2"})
    assert len(h) == 2
    recent = h.recent()
    assert [r["prompt"] for r in recent] == ["p2", "p1"]  # 最新在前
    first = h.recent(1)[0]
    assert first["index"] == 2
    assert "timestamp" in first
    h.clear()
    assert len(h) == 0
    assert h.recent() == []


def test_runhistory_creates_parent_dirs_and_reloads(tmp_path):
    path = tmp_path / "nested" / "dir" / "runs.jsonl"
    h = RunHistory(str(path))
    h.append({"prompt": "p"})
    h2 = RunHistory(str(path))  # 重新打开应延续已有记录与序号
    assert len(h2) == 1
    assert h2.recent()[0]["prompt"] == "p"
    assert h2.append({"prompt": "q"})["index"] == 2


def test_runhistory_creates_file_with_0600_permissions(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX 权限位在 Windows 上不适用")
    path = tmp_path / "private-runs.jsonl"
    h = RunHistory(str(path))
    h.append({"prompt": "secret"})
    assert os.stat(str(path)).st_mode & 0o777 == 0o600


def test_runhistory_concurrent_append_keeps_all(tmp_path):
    h = RunHistory(str(tmp_path / "runs.jsonl"))
    errors = []

    def worker(n):
        try:
            for i in range(20):
                h.append({"worker": n, "i": i})
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(h) == 80
    assert len(h.recent(1000)) == 80


# -- adapter 集成 ------------------------------------------------------------
def _adapter(history=None):
    coord = AgentCoordinator()
    register_demo_agents(coord)
    return DeepseekAdapter(coord, history=history)


def test_adapter_records_runs_and_answers_history_event(tmp_path):
    h = RunHistory(str(tmp_path / "runs.jsonl"))
    adapter = _adapter(history=h)
    result = adapter.handle_harness_event(
        {"type": "run", "prompt": "你好", "strategy": "broadcast", "rounds": 1}
    )
    assert "error" not in result
    assert len(h) == 1
    rec = h.recent()[0]
    assert rec["strategy"] == "broadcast"
    assert rec["prompt"] == "你好"
    assert rec["final"]
    assert rec["rounds"] == 1
    assert "elapsed_seconds" in rec
    out = adapter.handle_harness_event({"type": "history", "limit": 5})
    assert [r["prompt"] for r in out["records"]] == ["你好"]


def test_adapter_history_event_disabled():
    adapter = _adapter()  # 未启用 history
    assert adapter.handle_harness_event({"type": "history"}) == {"records": [], "enabled": False}


def test_adapter_failed_run_not_recorded(tmp_path):
    h = RunHistory(str(tmp_path / "runs.jsonl"))
    adapter = _adapter(history=h)
    out = adapter.handle_harness_event({"type": "run", "prompt": "", "strategy": "broadcast"})
    assert "error" in out
    assert len(h) == 0


def test_adapter_history_truncates_prompt_and_final(tmp_path):
    h = RunHistory(str(tmp_path / "runs.jsonl"))
    coord = AgentCoordinator()
    register_demo_agents(coord)
    adapter = DeepseekAdapter(
        coord,
        history=h,
        history_prompt_limit=5,
        history_final_limit=3,
    )
    result = adapter.handle_harness_event(
        {"type": "run", "prompt": "这是一个很长的任务提示词", "strategy": "broadcast", "rounds": 1}
    )
    assert "error" not in result
    rec = h.recent()[0]
    assert rec["prompt"] == "这是一个很…"
    assert rec["prompt"].endswith("…")
    assert len(rec["final"]) == 4  # 3 chars + ellipsis


# -- HTTP 端点 ---------------------------------------------------------------
def _http_server(history=None):
    coord = AgentCoordinator()
    register_demo_agents(coord)
    server = build_server("127.0.0.1", 0, coord, history=history)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _get(server, path):
    with urlreq.urlopen("http://127.0.0.1:{0}{1}".format(server.server_port, path), timeout=10) as resp:
        return json.loads(resp.read().decode())


def _post(server, path, payload):
    req = urlreq.Request(
        "http://127.0.0.1:{0}{1}".format(server.server_port, path),
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlreq.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def test_http_history_endpoint_roundtrip(tmp_path):
    h = RunHistory(str(tmp_path / "runs.jsonl"))
    server = _http_server(history=h)
    try:
        health = _get(server, "/health")
        assert health["history"] == "on"
        assert health["history_count"] == 0
        _post(server, "/run", {"type": "run", "prompt": "任务", "strategy": "broadcast", "rounds": 1})
        assert len(h) == 1
        data = _get(server, "/history?limit=10")
        assert len(data["records"]) == 1
        assert data["records"][0]["prompt"] == "任务"
        assert _get(server, "/health")["history_count"] == 1
    finally:
        server.shutdown()
        server.server_close()


def test_http_history_disabled_reports_enabled_false():
    server = _http_server()
    try:
        assert _get(server, "/health")["status"] == "ok"
        assert _get(server, "/history") == {"records": [], "enabled": False}
    finally:
        server.shutdown()
        server.server_close()


# -- MCP 工具 ----------------------------------------------------------------
def _mcp(history=None):
    coord = AgentCoordinator()
    register_demo_agents(coord)
    return McpServer(DeepseekAdapter(coord, history=history))


def _rpc(server, method, params=None, req_id=1):
    req = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        req["params"] = params
    return server.handle_request(req)


def test_mcp_tools_list_contains_history():
    resp = _rpc(_mcp(), "tools/list")
    names = [t["name"] for t in resp["result"]["tools"]]
    assert "history" in names


def test_mcp_history_tool_returns_records(tmp_path):
    h = RunHistory(str(tmp_path / "runs.jsonl"))
    server = _mcp(history=h)
    _rpc(server, "tools/call", {"name": "run", "arguments": {"prompt": "hi", "strategy": "broadcast", "rounds": 1}})
    resp = _rpc(server, "tools/call", {"name": "history", "arguments": {"limit": 5}}, req_id=2)
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert len(payload["records"]) == 1
    assert payload["records"][0]["prompt"] == "hi"
