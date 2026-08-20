# -*- coding: utf-8 -*-
"""End-to-end tests: CLI subprocess, HTTP adapter over a real socket,
MCP stdio server subprocess, and a full LLM round trip against a local
fake OpenAI-compatible API."""
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import deepseek_multi_agent_plugin as _pkg
from deepseek_multi_agent_plugin import AgentCoordinator, AgentFactory

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args, timeout=60):
    env = dict(os.environ)
    # 子进程管道输出固定为 UTF-8，避免 Windows 默认代码页（GBK）破坏中文内容解析
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, "-m", "deepseek_multi_agent_plugin.cli", *args],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=env, timeout=timeout,
    )
    return proc


# ---------------------------------------------------------------- CLI E2E ---
def test_cli_version():
    proc = _run_cli("--version")
    assert proc.returncode == 0
    assert proc.stdout.strip().endswith(_pkg.__version__)


def test_cli_run_demo_broadcast():
    proc = _run_cli("run", "--demo", "--strategy", "broadcast",
                    "--rounds", "1", "--prompt", "你好")
    assert proc.returncode == 0, proc.stderr
    assert "== FINAL ==" in proc.stdout
    assert "alpha received" in proc.stdout


def test_cli_run_with_trace_and_usage():
    proc = _run_cli("run", "--demo", "--strategy", "debate", "--rounds", "1",
                    "--prompt", "hi", "--trace", "--usage")
    assert proc.returncode == 0, proc.stderr
    assert "== TRACE ==" in proc.stdout
    assert '"run_id"' in proc.stdout
    assert "== USAGE ==" in proc.stdout


def test_cli_agents_json():
    proc = _run_cli("agents", "--demo", "--json")
    assert proc.returncode == 0, proc.stderr
    agents = json.loads(proc.stdout)
    assert {a["name"] for a in agents} == {"alpha", "beta"}


# --------------------------------------------------------------- HTTP E2E ---
class _Server:
    def __init__(self, **server_kwargs):
        from deepseek_multi_agent_plugin.adapter_server import build_server, register_demo_agents
        coord = AgentCoordinator()
        register_demo_agents(coord)
        self.httpd = build_server("127.0.0.1", 0, coord, **server_kwargs)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def post(self, path, obj, content_type="application/json"):
        data = json.dumps(obj).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={"Content-Type": content_type})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))


@pytest.fixture()
def server():
    s = _Server()
    yield s
    s.close()


def test_http_health_status_agents(server):
    code, body = server.get("/health")
    assert code == 200 and body["status"] == "ok" and body["version"] == _pkg.__version__
    code, body = server.get("/status")
    assert code == 200
    assert {a["name"] for a in body["agents"]} == {"alpha", "beta"}
    assert all("health" in a for a in body["agents"])
    code, body = server.get("/agents")
    assert code == 200 and len(body["agents"]) == 2


def test_http_run_and_runs_trace(server):
    code, body = server.post("/run", {"type": "run", "prompt": "任务",
                                      "strategy": "broadcast", "rounds": 1})
    assert code == 200
    assert "alpha received" in body["final"]
    run_id = body["meta"]["run_id"]
    code, body = server.get("/runs")
    assert code == 200 and body["runs"][0]["run_id"] == run_id
    code, body = server.get(f"/runs/{run_id}")
    assert code == 200
    assert len(body["span_list"]) == 2
    assert body["task_list"]
    code, _ = server.get("/runs/nonexistent00")
    assert code == 404


def test_http_rejects_bad_json(server):
    req = urllib.request.Request(server.base + "/run", data=b"{not json",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            code = resp.status
    except urllib.error.HTTPError as e:
        code = e.code
    assert code == 400


def test_http_rejects_huge_body(server):
    import http.client
    port = server.httpd.server_port
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        # 只声明超大 Content-Length、不真正上传：服务端必须在读 body 前拒绝。
        # 拒绝表现为 413 响应；Windows 上服务器未读完 body 就关闭连接时，
        # 客户端还可能看到 socket 半关闭竞态（ConnectionError 系）——
        # 同样证明服务器没有接受超大请求。
        conn.putrequest("POST", "/run")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(2 * 1024 * 1024))
        conn.endheaders()
        conn.send(b'{"type": "run"')
        try:
            resp = conn.getresponse()
        except OSError:
            return  # 服务端主动断开连接 = 已拒绝超大请求
        assert resp.status == 413
    finally:
        conn.close()


def test_http_token_auth(server):
    secured = _Server(token="s3cret")
    try:
        code, body = secured.get("/health")
        assert code == 401
        req = urllib.request.Request(
            secured.base + "/health", headers={"Authorization": "Bearer s3cret"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200
    finally:
        secured.close()


def test_http_register_unknown_kind_is_client_error(server):
    code, body = server.post("/register", {"type": "register",
                                           "agents": [{"name": "bad", "kind": "nope"}]})
    assert code == 400
    assert "invalid agent config" in body["error"]


def test_http_404(server):
    code, _ = server.get("/nope")
    assert code == 404


# --------------------------------------------------------------- MCP E2E ----
def test_mcp_stdio_roundtrip():
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "t", "version": "0"}}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "run",
                               "arguments": {"prompt": "hi", "strategy": "broadcast"}}}),
        json.dumps({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                    "params": {"name": "runs", "arguments": {"limit": 5}}}),
        json.dumps({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                    "params": {"name": "status", "arguments": {}}}),
        json.dumps({"jsonrpc": "2.0", "id": 6, "method": "bogus/method"}),
        "not json at all",
    ]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, "-m", "deepseek_multi_agent_plugin.mcp_server", "--demo"],
        input="\n".join(lines) + "\n", capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    responses = {}
    for line in proc.stdout.strip().splitlines():
        msg = json.loads(line)
        if "id" in msg:
            responses[msg["id"]] = msg
    assert responses[1]["result"]["protocolVersion"] == "2025-06-18"
    tool_names = {t["name"] for t in responses[2]["result"]["tools"]}
    assert tool_names == {"run", "agents", "register", "status", "history", "runs"}
    payload = json.loads(responses[3]["result"]["content"][0]["text"])
    assert payload["strategy"] == "broadcast" and payload["final"]
    runs = json.loads(responses[4]["result"]["content"][0]["text"])
    assert runs["runs"] and runs["runs"][0]["spans"] == 2
    status = json.loads(responses[5]["result"]["content"][0]["text"])
    assert status["status"] == "ok" and status["version"]
    assert responses[6]["error"]["code"] == -32601


# ------------------------------------------------- real LLM path with fake ---
class _FakeLLMHandler(BaseHTTPRequestHandler):
    calls = 0

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        _FakeLLMHandler.calls += 1
        body = json.dumps({
            "choices": [{"message": {"content": f"llm-reply-{_FakeLLMHandler.calls}"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_e2e_llm_round_trip_with_usage():
    _FakeLLMHandler.calls = 0
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _FakeLLMHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_port}"
    try:
        coord = AgentCoordinator()
        for n in ("r1", "r2"):
            coord.register_agent(AgentFactory.create_agent(
                "deepseek", n, api_key="test-key", base_url=base))
        result = coord.run("hello", strategy="broadcast", rounds=1)
        assert result["final"].count("llm-reply") == 2
        usage = result["meta"]["usage"]
        assert usage["total"]["total_tokens"] == 30
        assert usage["agents"]["r1"]["total_tokens"] == 15
        trace = coord.runs.get(result["meta"]["run_id"])
        assert len(trace.spans) == 2
    finally:
        httpd.shutdown()
        httpd.server_close()
