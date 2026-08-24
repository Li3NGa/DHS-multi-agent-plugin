"""Regression tests for the audit-P0 batch (E4 merge-gate follow-up).

Covers:
  1. executor slot-leak on cancelled queued futures (P0 #1)
  2. CLI serve subcommand import (P0 #4)
  3. MCP stdio survives malformed initialize / garbage lines (P0 #3)
  4. register secure-default kind gate + atomicity + sanitized errors (P0 #2)
"""
import io
import json
import sys
import threading
import time

from deepseek_multi_agent_plugin.coordinator import AgentCoordinator, DeepseekAdapter
from deepseek_multi_agent_plugin.runtime.executor import PoolSaturated, _BoundedExecutor


# --------------------------------------------------------------- 1. slots ---
def test_cancelled_queued_future_does_not_leak_slot():
    pool = _BoundedExecutor(2)
    gate = threading.Event()
    pool.submit(lambda: gate.wait(5))
    pool.submit(lambda: gate.wait(5))
    time.sleep(0.2)

    threading.Thread(
        target=lambda: (time.sleep(0.15), gate.set()), daemon=True
    ).start()

    queued = None
    deadline = time.time() + 3
    while time.time() < deadline:
        try:
            queued = pool.submit(lambda: None)
            break
        except PoolSaturated:
            time.sleep(0.01)
    assert queued is not None, "could not obtain a queued future"
    if not queued.cancel():
        return  # worker won the dequeue race; nothing to assert this round

    gate.set()
    time.sleep(0.3)

    # Both probes must hold slots AT THE SAME TIME: barrier(2) blocks the
    # first task until the second one arrives, so 'ok' requires two live
    # slots even though nothing else is running.
    results = []
    barrier = threading.Barrier(2, timeout=5)

    def probe(_index):
        try:
            pool.submit(barrier.wait).result(timeout=6)
            results.append("ok")
        except Exception as exc:
            results.append(type(exc).__name__)

    threads = [threading.Thread(target=probe, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert sorted(results) == ["ok", "ok"], results


# ------------------------------------------------------------ 2. cli serve ---
def test_serve_subcommand_reaches_http_serve(monkeypatch):
    from deepseek_multi_agent_plugin.adapters import cli as cli_mod
    from deepseek_multi_agent_plugin.adapters import http as http_mod

    captured = {}

    def fake_serve(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

    monkeypatch.setattr(http_mod, "serve", fake_serve)
    cli_mod.main(["serve", "--demo", "--port", "0"])
    assert captured["args"][1] == 0
    assert captured["args"][2].agent_names == ["alpha", "beta"]


# ---------------------------------------------------------------- 3. mcp ----
def _mcp_session(lines):
    from deepseek_multi_agent_plugin.adapters.mcp import McpServer

    srv = McpServer(DeepseekAdapter(AgentCoordinator()))
    out = io.StringIO()
    srv.serve(iter(lines), out)
    return out.getvalue()


def test_mcp_survives_malformed_initialize_params():
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1,
                    "method": "initialize", "params": ["evil"]}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}),
    ]
    out = _mcp_session(lines)
    # the stdio loop is still alive and answered the follow-up ping
    assert '"id": 2' in out


def test_mcp_survives_garbage_line_then_answers_ping():
    lines = [
        "{not json",
        json.dumps({"jsonrpc": "2.0", "id": 7, "method": "ping"}),
    ]
    out = _mcp_session(lines)
    assert '"id": 7' in out


# ------------------------------------------------------- 4. register gate ---
def _cli_config():
    return {"name": "shell", "kind": "cli",
            "command": sys.executable, "args": ["-c", "print(46)]"]}


def _adapter(**kwargs):
    return DeepseekAdapter(AgentCoordinator(), **kwargs)


def test_register_denies_cli_by_default():
    adapter = _adapter()
    result = adapter.handle_harness_event(
        {"type": "register", "agents": [dict(_cli_config())]}
    )
    assert "error" in result
    assert "opt-in" in result["error"]
    assert adapter.coordinator.agent_names == []


def test_register_opt_in_allows_cli_and_registers_it():
    adapter = _adapter()
    adapter.allowed_register_kinds = frozenset(
        {"mock", "echo", "deepseek", "openai", "cli"}
    )
    result = adapter.handle_harness_event(
        {"type": "register", "agents": [dict(_cli_config())]}
    )
    assert result.get("registered") == ["shell"]
    assert adapter.coordinator.agent_names == ["shell"]


def test_register_is_atomic_on_invalid_config():
    adapter = _adapter()
    result = adapter.handle_harness_event(
        {"type": "register", "agents": [
            {"name": "good", "kind": "mock"},
            {"name": "bad", "kind": "nope"},
            {"name": "never", "kind": "mock"},
        ]}
    )
    assert "error" in result
    assert adapter.coordinator.agent_names == []
    assert "nope" not in json.dumps(result)


def test_register_sanitizes_factory_error_detail():
    adapter = _adapter()
    adapter.allowed_register_kinds = frozenset({"cli"})
    broken_cli = {"name": "broken", "kind": "cli", "args": ["-c", "x"]}
    result = adapter.handle_harness_event(
        {"type": "register", "agents": [broken_cli]}
    )
    assert result["error"].startswith("invalid agent config")
    assert "command" not in result["error"]
