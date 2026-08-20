"""Integration tests for the HTTP adapter server."""
import json
import logging
import threading
from http.server import ThreadingHTTPServer
from urllib import request as urlreq

import deepseek_multi_agent_plugin.adapters.http as adapter_mod
from deepseek_multi_agent_plugin.adapters.http import AdapterHandler, build_server, register_demo_agents
from deepseek_multi_agent_plugin.coordinator import AgentCoordinator, DeepseekAdapter


def _start_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), AdapterHandler)
    coord = AgentCoordinator()
    register_demo_agents(coord)
    server.adapter = DeepseekAdapter(coord)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _get(server, path):
    with urlreq.urlopen(f"http://127.0.0.1:{server.server_port}{path}", timeout=10) as resp:
        return json.loads(resp.read().decode())


def _post(server, path, payload):
    req = urlreq.Request(
        f"http://127.0.0.1:{server.server_port}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlreq.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def test_health():
    server = _start_server()
    try:
        assert _get(server, "/health")["status"] == "ok"
    finally:
        server.shutdown()
        server.server_close()


def test_agents_endpoint():
    server = _start_server()
    try:
        out = _get(server, "/agents")
        assert {a["name"] for a in out["agents"]} == {"alpha", "beta"}
    finally:
        server.shutdown()
        server.server_close()


def test_run_broadcast():
    server = _start_server()
    try:
        out = _post(server, "/run",
                    {"type": "run", "prompt": "hello", "strategy": "broadcast", "rounds": 1})
        assert out["strategy"] == "broadcast"
        assert "alpha received" in out["final"]
        assert "beta processed" in out["final"]
    finally:
        server.shutdown()
        server.server_close()


def test_run_debate_default_strategy():
    server = _start_server()
    try:
        out = _post(server, "/run", {"type": "run", "prompt": "hello", "rounds": 1})
        assert out["strategy"] == "debate"
    finally:
        server.shutdown()
        server.server_close()


def test_run_missing_prompt():
    server = _start_server()
    try:
        try:
            _post(server, "/run", {"type": "run"})
            raise AssertionError("expected HTTP error")
        except urlreq.HTTPError as exc:
            assert exc.code == 400
            body = json.loads(exc.read().decode())
            assert body == {"error": "missing prompt"}
    finally:
        server.shutdown()
        server.server_close()


def test_register_endpoint():
    server = _start_server()
    try:
        out = _post(server, "/register",
                    {"type": "register", "agents": [{"name": "gamma", "kind": "echo"}]})
        assert out == {"registered": ["gamma"]}
        agents = _get(server, "/agents")
        assert {a["name"] for a in agents["agents"]} == {"alpha", "beta", "gamma"}
    finally:
        server.shutdown()
        server.server_close()


def test_status_event():
    server = _start_server()
    try:
        out = _post(server, "/run", {"type": "status"})
        assert out["status"] == "ok"
    finally:
        server.shutdown()
        server.server_close()


def test_invalid_json_returns_400():
    server = _start_server()
    try:
        req = urlreq.Request(
            f"http://127.0.0.1:{server.server_port}/run",
            data=b"{not json",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlreq.urlopen(req, timeout=10):
                raise AssertionError("expected HTTP error")
        except urlreq.HTTPError as exc:
            assert exc.code == 400
            body = json.loads(exc.read().decode())
            assert "error" in body
        else:
            raise AssertionError("expected HTTP error")
    finally:
        server.shutdown()
        server.server_close()


def test_not_found():
    server = _start_server()
    try:
        try:
            with urlreq.urlopen(f"http://127.0.0.1:{server.server_port}/nope", timeout=10):
                raise AssertionError("expected HTTP error")
        except urlreq.HTTPError as exc:
            assert exc.code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_register_invalid_agent_returns_400():
    server = _start_server()
    try:
        req = urlreq.Request(
            f"http://127.0.0.1:{server.server_port}/register",
            data=json.dumps({"type": "register", "agents": [{}]}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlreq.urlopen(req, timeout=10):
                raise AssertionError("expected HTTP error")
        except urlreq.HTTPError as exc:
            assert exc.code == 400
            body = json.loads(exc.read().decode())
            assert "invalid agent config" in body["error"]
    finally:
        server.shutdown()
        server.server_close()


def test_build_server_shuts_down_cleanly():
    coord = AgentCoordinator()
    register_demo_agents(coord)
    server = build_server("127.0.0.1", 0, coord)
    assert server.daemon_threads is True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)
    assert not thread.is_alive()


def test_oversized_body_returns_413(monkeypatch):
    monkeypatch.setattr(adapter_mod, "MAX_REQUEST_BYTES", 64)
    server = _start_server()
    try:
        req = urlreq.Request(
            f"http://127.0.0.1:{server.server_port}/run",
            data=b"x" * 128,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlreq.urlopen(req, timeout=10):
                raise AssertionError("expected HTTP error")
        except urlreq.HTTPError as exc:
            assert exc.code == 413
            body = json.loads(exc.read().decode())
            assert body == {"error": "request body too large"}
    finally:
        server.shutdown()
        server.server_close()


def test_token_auth_required():
    coord = AgentCoordinator()
    register_demo_agents(coord)
    server = build_server("127.0.0.1", 0, coord, token="s3cret")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        try:
            _get(server, "/health")
            raise AssertionError("expected 401 without token")
        except urlreq.HTTPError as exc:
            assert exc.code == 401

        req = urlreq.Request(
            f"http://127.0.0.1:{server.server_port}/health",
            headers={"Authorization": "Bearer s3cret"},
        )
        with urlreq.urlopen(req, timeout=10) as resp:
            assert json.loads(resp.read().decode())["status"] == "ok"

        try:
            req = urlreq.Request(
                f"http://127.0.0.1:{server.server_port}/health",
                headers={"Authorization": "Bearer wrong"},
            )
            with urlreq.urlopen(req, timeout=10):
                raise AssertionError("expected 401 with wrong token")
        except urlreq.HTTPError as exc:
            assert exc.code == 401
    finally:
        server.shutdown()
        server.server_close()


def test_log_message_redacts_bearer_token(caplog):
    caplog.set_level(logging.INFO, logger="deepseek-multi-agent-plugin")
    handler = object.__new__(AdapterHandler)
    handler.address_string = lambda: "127.0.0.1"
    handler.log_message('"%s" Authorization: Bearer %s', "GET /run HTTP/1.1", "sk-test-123")
    assert "sk-test-123" not in caplog.text
    assert "Bearer ***" in caplog.text


def test_adapter_exception_detail_is_fixed_and_redacted(caplog):
    caplog.set_level(logging.INFO, logger="deepseek-multi-agent-plugin")
    server = build_server("127.0.0.1", 0, AgentCoordinator(), token="sk-test-123")

    def boom(event):
        raise RuntimeError("boom sk-test-123")

    server.adapter.handle_harness_event = boom
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        req = urlreq.Request(
            f"http://127.0.0.1:{server.server_port}/run",
            data=json.dumps({"type": "run", "prompt": "hi", "strategy": "broadcast"}).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer sk-test-123",
            },
        )
        try:
            with urlreq.urlopen(req, timeout=10):
                raise AssertionError("expected HTTP error")
        except urlreq.HTTPError as exc:
            assert exc.code == 500
            body = json.loads(exc.read().decode())
            assert body["detail"] == "internal adapter error"
            assert "boom" not in body["detail"]
            assert "sk-test-123" not in body["detail"]
        assert "sk-test-123" not in caplog.text
    finally:
        server.shutdown()
        server.server_close()
