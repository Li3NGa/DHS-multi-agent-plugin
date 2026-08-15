"""HTTP adapter server for the DeepSeek harness.

Endpoints:

  GET  /health     -> {"status": "ok"}
  GET  /agents     -> registered agents
  POST /run        -> {"type": "run", "prompt": "...", "strategy": "...", ...}
  POST /register   -> {"type": "register", "agents": [{name, kind, ...}]}

The server uses only the Python standard library. Example:

  python -m deepseek_multi_agent_plugin.adapter_server --port 8000 --demo

  curl -X POST localhost:8000/run -H "Content-Type: application/json" \\
       -d '{"type": "run", "prompt": "你好", "strategy": "debate", "rounds": 1}'
"""
import argparse
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Tuple

from .agents import Agent, AgentFactory
from .config import build_coordinator
from .coordinator import AgentCoordinator, DeepseekAdapter

log = logging.getLogger("deepseek-multi-agent-plugin")


class AdapterHandler(BaseHTTPRequestHandler):
    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_event(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            event = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ValueError(f"invalid json: {exc}") from exc
        if not isinstance(event, dict):
            raise ValueError("event must be a JSON object")
        return event

    def do_GET(self):
        if self.path.split("?")[0] == "/health":
            self._send_json({"status": "ok"})
        elif self.path.split("?")[0] == "/agents":
            adapter = self.server.adapter
            self._send_json({"agents": [a.describe() for a in adapter.coordinator.agents]})
        else:
            self._send_json({"error": "not found"}, code=404)

    def do_POST(self):
        path = self.path.split("?")[0]
        if path not in ("/run", "/register"):
            self._send_json({"error": "not found"}, code=404)
            return
        try:
            event = self._read_event()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, code=400)
            return
        try:
            result = self.server.adapter.handle_harness_event(event)
            code = 400 if "error" in result and event.get("type") == "run" else 200
            self._send_json(result, code=code)
        except Exception as exc:
            log.exception("adapter error")
            self._send_json({"error": "adapter error", "detail": str(exc)}, code=500)

    def log_message(self, fmt, *args):
        log.info("%s - %s", self.address_string(), fmt % args)


def register_demo_agents(coordinator: AgentCoordinator) -> None:
    """Register two mock agents for local testing."""
    coordinator.register_agent(
        AgentFactory.create_agent('mock', 'alpha', message_template='alpha received: {msg}')
    )
    coordinator.register_agent(
        AgentFactory.create_agent('mock', 'beta', message_template='beta processed: {msg}')
    )


def serve(host: str, port: int, coordinator: AgentCoordinator) -> None:
    server = ThreadingHTTPServer((host, port), AdapterHandler)
    server.adapter = DeepseekAdapter(coordinator)
    log.info("adapter server listening on http://%s:%s (agents: %s)",
             host, port, coordinator.agent_names)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        server.server_close()


def main(argv: Optional[Tuple[str, ...]] = None) -> None:
    parser = argparse.ArgumentParser(description="Deepseek multi-agent plugin HTTP adapter")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--config", default=None, help="YAML/JSON agent config file")
    parser.add_argument("--demo", action="store_true", help="register demo mock agents")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.config:
        coord = build_coordinator(path=args.config)
    else:
        coord = AgentCoordinator()
        if args.demo:
            register_demo_agents(coord)
    serve(args.host, args.port, coord)


if __name__ == "__main__":
    main()
