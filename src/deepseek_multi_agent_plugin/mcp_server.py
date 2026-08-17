"""MCP (Model Context Protocol) stdio server for the multi-agent plugin.

Exposes the collaboration engine to MCP hosts (DSH's dsh-mcp-client, Codex,
Claude Code, ...) over newline-delimited JSON-RPC on stdin/stdout, using only
the Python standard library. The DSH web profile hot-loads MCP servers via
its cordis.patch.yml; Codex uses [mcp_servers.<name>] in config.toml.

Tools exposed (server-qualified by the host, e.g. mcp__multiagent__run):

  run        -> run a multi-agent collaboration strategy
  agents     -> list registered agents
  register   -> register agents from config dicts
  status     -> adapter status summary
  history    -> recent run records (when started with --history)
  runs       -> recent run traces / one full trace by run_id

Usage:

  python -m deepseek_multi_agent_plugin.mcp_server --demo
  python -m deepseek_multi_agent_plugin.mcp_server --config agents.yaml
"""
import argparse
import json
import logging
import os
import sys
from typing import Any, Dict, Optional

from .adapter_server import SessionRegistry, register_demo_agents
from .agents import AgentFactory
from .config import build_coordinator, load_dsh_credentials
from .coordinator import AgentCoordinator, DeepseekAdapter
from .history import RunHistory
from .strategies import STRATEGY_NAMES

log = logging.getLogger("deepseek-multi-agent-plugin.mcp")

PROTOCOL_VERSION = "2025-03-26"
# 实测来自本机 @modelcontextprotocol/sdk 的 SUPPORTED_PROTOCOL_VERSIONS
# （LATEST_PROTOCOL_VERSION = 2025-11-25）。
SUPPORTED_PROTOCOL_VERSIONS = {
    "2025-03-26",
    "2025-06-18",
    "2025-11-25",
    "2024-11-05",
    "2024-10-07",
}

_STRATEGIES = list(STRATEGY_NAMES)

_TOOLS: Dict[str, Dict[str, Any]] = {
    "run": {
        "description": (
            "Run a multi-agent collaboration strategy and return the final "
            "answer plus per-round details. Strategies: broadcast (parallel "
            "discussion), sequential (chain-of-agents), debate (multi-round "
            "with judge), supervisor (task decomposition + parallel workers), "
            "consensus (propose + vote), relay (pass-the-baton draft refinement)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "The task or question for the agents."},
                "strategy": {"type": "string", "enum": _STRATEGIES},
                "rounds": {"type": "integer", "minimum": 1, "description": "Debate/broadcast rounds (default 1)."},
                "session_id": {"type": "string", "description": "Optional session id; isolates memory and registry per session."},
                "judge": {"type": "string", "description": "Debate/consensus judge agent name."},
                "order": {"type": "array", "items": {"type": "string"}, "description": "Sequential strategy speaking order."},
                "workers": {"type": "array", "items": {"type": "string"}, "description": "Supervisor worker agent names."},
                "timeout": {"type": "number", "description": "Per-agent timeout in seconds."},
            },
            "required": ["prompt"],
        },
    },
    "agents": {
        "description": "List registered agents (name, role, provider, model, token usage).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "register": {
        "description": (
            "Register agents. Each entry: {name, kind: mock|echo|http|deepseek|"
            "openai|custom, plus kind-specific fields like system_prompt, "
            "model, url}."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "agents": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Agent config dicts (same shape as the HTTP register event).",
                },
            },
            "required": ["agents"],
        },
    },
    "status": {
        "description": "Adapter status: agent names, auto strategy, session count.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "history": {
        "description": "查询最近的多智能体协作运行历史（需服务以 --history 启动），返回最新在前的记录列表。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "description": "返回最近 N 条记录（默认 20）。"},
            },
        },
    },
    "runs": {
        "description": (
            "查询最近运行的 trace（可观测性）。不带 run_id 时返回最近运行的"
            "摘要列表；带 run_id 时返回该次运行的完整 span/task 明细。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "指定 run 的 id（meta.run_id），返回完整明细。"},
                "limit": {"type": "integer", "minimum": 1, "description": "摘要列表长度（默认 20）。"},
            },
        },
    },
}


class McpServer:
    """Minimal MCP stdio JSON-RPC server bound to a DeepseekAdapter."""

    def __init__(self, adapter: DeepseekAdapter):
        self.adapter = adapter

    # -- tool implementations -------------------------------------------
    def _call_tool(self, name: str, args: Dict[str, Any]) -> Any:
        event: Dict[str, Any] = dict(args)
        event["type"] = name
        if name == "run":
            result = self.adapter.handle_harness_event(event)
            if "error" in result:
                raise ValueError(str(result["error"]))
            return result
        if name == "agents":
            return self.adapter.handle_harness_event(
                {"type": "agents", "session_id": args.get("session_id")}
            )
        if name == "register":
            return self.adapter.handle_harness_event(event)
        if name == "status":
            out = self.adapter.handle_harness_event(
                {"type": "status", "session_id": args.get("session_id")}
            )
            out["version"] = self._version()
            registry = getattr(self.adapter, "registry", None)
            if registry is not None:
                out["sessions"] = len(registry)
            return out
        if name == "history":
            return self.adapter.handle_harness_event(
                {"type": "history", "limit": args.get("limit")}
            )
        if name == "runs":
            coord_registry = getattr(self.adapter.coordinator, "runs", None)
            if coord_registry is None:
                return {"runs": []}
            run_id = args.get("run_id")
            if run_id:
                trace = coord_registry.get(str(run_id))
                if trace is None:
                    raise ValueError(f"run not found: {run_id}")
                return trace.to_dict()
            return {"runs": coord_registry.recent(int(args.get("limit") or 20))}
        raise ValueError(f"unknown tool: {name}")

    # -- JSON-RPC plumbing ----------------------------------------------
    def handle_request(self, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        method = req.get("method", "")
        req_id = req.get("id")
        if method == "initialize":
            params = req.get("params") or {}
            requested = params.get("protocolVersion", PROTOCOL_VERSION)
            negotiated = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
            return self._result(req_id, {
                "protocolVersion": negotiated,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "deepseek-multi-agent-plugin",
                    "version": self._version(),
                },
            })
        if method == "notifications/initialized":
            return None
        if method == "ping":
            return self._result(req_id, {})
        if method == "tools/list":
            return self._result(req_id, {
                "tools": [
                    {"name": n, "description": t["description"], "inputSchema": t["inputSchema"]}
                    for n, t in _TOOLS.items()
                ]
            })
        if method == "tools/call":
            params = req.get("params") or {}
            try:
                value = self._call_tool(params.get("name", ""), params.get("arguments") or {})
                return self._result(req_id, {
                    "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
                })
            except Exception as exc:  # noqa: BLE001 - report tool errors on the wire
                return self._result(req_id, {
                    "content": [{"type": "text", "text": f"error: {exc}"}],
                    "isError": True,
                })
        if req_id is not None:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": f"method not found: {method}"}}
        return None

    @staticmethod
    def _result(req_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    @staticmethod
    def _version() -> str:
        try:
            from importlib.metadata import version
            return version("deepseek-multi-agent-plugin")
        except Exception:  # noqa: BLE001 - optional metadata
            return "0.0.0"

    def serve(self, stdin=None, stdout=None) -> None:
        """Read newline-delimited JSON-RPC requests until EOF."""
        stdin = stdin if stdin is not None else sys.stdin
        stdout = stdout if stdout is not None else sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except ValueError:
                if stdout is not None:
                    stdout.write(json.dumps({
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "Parse error"},
                    }) + "\n")
                    stdout.flush()
                continue
            if not isinstance(req, dict):
                if stdout is not None:
                    stdout.write(json.dumps({
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32600, "message": "Invalid Request"},
                    }) + "\n")
                    stdout.flush()
                continue
            resp = self.handle_request(req)
            if resp is not None:
                stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                stdout.flush()


def _session_registry(config=None) -> SessionRegistry:
    if config is not None:
        return SessionRegistry(factory=lambda: build_coordinator(config=dict(config)))
    return SessionRegistry()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="MCP stdio server (multi-agent plugin)")
    parser.add_argument("--config", default=None, help="YAML/JSON agent config file")
    parser.add_argument("--demo", action="store_true", help="register demo mock agents")
    parser.add_argument("--history", default=None, help="run history JSONL file (enables the history tool)")
    parser.add_argument("--history-prompt-limit", type=int, default=None,
                        help="truncate persisted prompts to N chars (default: no truncation)")
    parser.add_argument("--history-final-limit", type=int, default=None,
                        help="truncate persisted final answers to N chars (default: no truncation)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=os.environ.get("MCP_LOG_LEVEL", "ERROR"),
                        stream=sys.stderr)
    load_dsh_credentials()  # DEEPSEEK_API_KEY from ~/.dsh/.credentials.yaml if present
    if args.config:
        from .config import load_config
        config = load_config(args.config)
        coord = build_coordinator(config=config)
        registry = _session_registry(config)
    elif args.demo:
        coord = AgentCoordinator()
        register_demo_agents(coord)

        def factory():
            c = AgentCoordinator()
            register_demo_agents(c)
            return c

        registry = SessionRegistry(factory=factory)
    else:
        coord = AgentCoordinator()
        registry = _session_registry()
    history = RunHistory(args.history) if args.history else None
    McpServer(DeepseekAdapter(
        coord,
        registry=registry,
        history=history,
        history_prompt_limit=args.history_prompt_limit,
        history_final_limit=args.history_final_limit,
    )).serve()


if __name__ == "__main__":
    main()
