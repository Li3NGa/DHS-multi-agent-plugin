"""Tests for the MCP stdio server."""
import io
import json

from deepseek_multi_agent_plugin import AgentCoordinator
from deepseek_multi_agent_plugin.adapter_server import SessionRegistry, register_demo_agents
from deepseek_multi_agent_plugin.coordinator import DeepseekAdapter
from deepseek_multi_agent_plugin.mcp_server import McpServer


def _server() -> McpServer:
    coord = AgentCoordinator()
    register_demo_agents(coord)
    return McpServer(DeepseekAdapter(coord, registry=SessionRegistry()))


def _rpc(server, method, params=None, req_id=1):
    req = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        req["params"] = params
    return server.handle_request(req)


def test_initialize():
    resp = _rpc(_server(), "initialize", {"protocolVersion": "2025-03-26"})
    assert resp["result"]["protocolVersion"] == "2025-03-26"
    assert "tools" in resp["result"]["capabilities"]
    assert resp["result"]["serverInfo"]["name"] == "deepseek-multi-agent-plugin"


def test_tools_list():
    resp = _rpc(_server(), "tools/list")
    names = [t["name"] for t in resp["result"]["tools"]]
    assert names == ["run", "agents", "register", "status"]
    run_tool = resp["result"]["tools"][0]
    assert run_tool["inputSchema"]["required"] == ["prompt"]
    assert "debate" in run_tool["inputSchema"]["properties"]["strategy"]["enum"]
    assert "relay" in run_tool["inputSchema"]["properties"]["strategy"]["enum"]


def test_tools_call_run():
    resp = _rpc(_server(), "tools/call",
                {"name": "run", "arguments": {"prompt": "hi", "strategy": "broadcast", "rounds": 1}})
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["strategy"] == "broadcast"
    assert "final" in payload and payload["final"]


def test_tools_call_run_missing_prompt_is_error():
    resp = _rpc(_server(), "tools/call", {"name": "run", "arguments": {}})
    assert resp["result"]["isError"] is True


def test_tools_call_agents_and_status():
    server = _server()
    agents = _rpc(server, "tools/call", {"name": "agents"}, req_id=2)
    names = json.loads(agents["result"]["content"][0]["text"])["agents"]
    assert [a["name"] for a in names] == ["alpha", "beta"]

    status = _rpc(server, "tools/call", {"name": "status"}, req_id=3)
    out = json.loads(status["result"]["content"][0]["text"])
    assert out["status"] == "ok"
    assert out["sessions"] == 0


def test_tools_call_register_with_session():
    server = _server()
    resp = _rpc(server, "tools/call",
                {"name": "register",
                 "arguments": {"session_id": "s1", "agents": [{"name": "gamma", "kind": "echo"}]}})
    assert json.loads(resp["result"]["content"][0]["text"]) == {"registered": ["gamma"]}
    agents = _rpc(server, "tools/call",
                  {"name": "agents", "arguments": {"session_id": "s1"}}, req_id=2)
    names = [a["name"] for a in json.loads(agents["result"]["content"][0]["text"])["agents"]]
    assert names == ["gamma"]  # sessions without a factory start empty
    default = _rpc(server, "tools/call", {"name": "agents"}, req_id=3)
    default_names = [a["name"] for a in json.loads(default["result"]["content"][0]["text"])["agents"]]
    assert default_names == ["alpha", "beta"]  # default coordinator untouched


def test_notifications_yield_no_response():
    assert _server().handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_unknown_method_returns_error():
    resp = _rpc(_server(), "no/such/method")
    assert resp["error"]["code"] == -32601


def test_serve_end_to_end_over_stdio():
    server = _server()
    stdin = io.StringIO("\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-03-26"}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "run",
                               "arguments": {"prompt": "hi", "strategy": "sequential"}}}),
        "not json at all",
    ]) + "\n")
    stdout = io.StringIO()
    server.serve(stdin=stdin, stdout=stdout)
    lines = [json.loads(l) for l in stdout.getvalue().strip().splitlines()]
    assert len(lines) == 3  # initialized notification produces no response; bad json skipped
    assert lines[0]["result"]["serverInfo"]["name"] == "deepseek-multi-agent-plugin"
    assert [t["name"] for t in lines[1]["result"]["tools"]] == ["run", "agents", "register", "status"]
    assert "final" in json.loads(lines[2]["result"]["content"][0]["text"])
