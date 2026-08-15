"""HTTP adapter server for the DeepSeek harness.

Endpoints:

  GET  /health     -> {"status": "ok"}
  GET  /agents     -> registered agents
  POST /run        -> {"type": "run", "prompt": "...", "strategy": "...", ...}
  POST /register   -> {"type": "register", "agents": [{name, kind, ...}]}

Events may carry an optional ``session_id``; sessions get isolated
coordinators (own agent registry + shared memory) via SessionRegistry, so
concurrent harness tasks never see each other's discussion history.

When a token is configured (--token or the DS_AGENT_TOKEN environment
variable), every request must send ``Authorization: Bearer <token>``.

The server uses only the Python standard library. Example:

  python -m deepseek_multi_agent_plugin.adapter_server --port 8000 --demo

  curl -X POST localhost:8000/run -H "Content-Type: application/json" \\
       -d '{"type": "run", "prompt": "你好", "strategy": "debate", "rounds": 1}'
"""
import argparse
import json
import logging
import os
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from typing import Callable, Dict, Optional, Tuple

from .agents import Agent, AgentFactory
from .config import build_coordinator
from .coordinator import AgentCoordinator, DeepseekAdapter

log = logging.getLogger("deepseek-multi-agent-plugin")


class SessionRegistry:
    """Map session ids to isolated AgentCoordinator instances.

    A ``factory`` callable builds a fresh coordinator per session (typically
    rebuilding the configured team); without one, empty coordinators are
    created (register agents per session via the ``register`` event).
    """

    def __init__(self, factory: Optional[Callable[[], AgentCoordinator]] = None):
        self._factory = factory
        self._sessions: Dict[str, AgentCoordinator] = {}
        self._lock = Lock()

    def get_or_create(self, session_id: str) -> AgentCoordinator:
        with self._lock:
            coord = self._sessions.get(session_id)
            if coord is None:
                coord = self._factory() if self._factory else AgentCoordinator()
                self._sessions[session_id] = coord
            return coord

    def session_ids(self):
        with self._lock:
            return list(self._sessions)

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)


class AdapterHandler(BaseHTTPRequestHandler):
    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        token = getattr(self.server, "auth_token", None)
        if not token:
            return True
        header = self.headers.get("Authorization") or ""
        return header == f"Bearer {token}"

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
        if not self._authorized():
            self._send_json({"error": "unauthorized"}, code=401)
            return
        if self.path.split("?")[0] == "/health":
            self._send_json({"status": "ok"})
        elif self.path.split("?")[0] == "/agents":
            adapter = self.server.adapter
            self._send_json({"agents": [a.describe() for a in adapter.coordinator.agents]})
        else:
            self._send_json({"error": "not found"}, code=404)

    def do_POST(self):
        if not self._authorized():
            self._send_json({"error": "unauthorized"}, code=401)
            return
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


def build_server(
    host: str,
    port: int,
    coordinator: AgentCoordinator,
    token: Optional[str] = None,
    session_factory: Optional[Callable[[], AgentCoordinator]] = None,
) -> ThreadingHTTPServer:
    """Create a configured adapter server without starting it.

    Exposed separately so tests and embedders can attach an already-running
    server (e.g. to verify graceful shutdown without blocking a thread).
    """
    server = ThreadingHTTPServer((host, port), AdapterHandler)
    # Hung agent calls must not keep the container alive forever during
    # graceful shutdown; daemon threads let ``server_close`` return promptly.
    server.daemon_threads = True
    registry = SessionRegistry(factory=session_factory) if session_factory else None
    server.adapter = DeepseekAdapter(coordinator, registry=registry)
    server.auth_token = token
    return server


def serve(
    host: str,
    port: int,
    coordinator: AgentCoordinator,
    token: Optional[str] = None,
    session_factory: Optional[Callable[[], AgentCoordinator]] = None,
) -> None:
    server = build_server(host, port, coordinator, token=token, session_factory=session_factory)
    log.info("adapter server listening on http://%s:%s (agents: %s, auth: %s, sessions: %s)",
             host, port, coordinator.agent_names,
             "on" if token else "off",
             "on" if session_factory else "off")

    def _shutdown_handler(signum, frame):  # noqa: ARG001 - signal API
        log.info("received signal %s, shutting down gracefully", signum)
        # ``shutdown`` must run outside the signal handler (it blocks until
        # serve_forever returns), so hand it to a short-lived daemon thread.
        threading.Thread(target=server.shutdown, daemon=True).start()

    if threading.current_thread() is threading.main_thread():
        for sig_name in ("SIGTERM", "SIGINT"):
            sig = getattr(signal, sig_name, None)
            if sig is not None:
                try:
                    signal.signal(sig, _shutdown_handler)
                except (ValueError, OSError):
                    # Not the main thread or unsupported signal; skip.
                    pass
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
    parser.add_argument("--token", default=os.environ.get("DS_AGENT_TOKEN"),
                        help="require 'Authorization: Bearer <token>' (default: $DS_AGENT_TOKEN)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.config:
        from .config import load_config
        config = load_config(args.config)
        coord = build_coordinator(config=config)
        session_factory = lambda: build_coordinator(config=dict(config))
    elif args.demo:
        coord = AgentCoordinator()

        def session_factory():
            c = AgentCoordinator()
            register_demo_agents(c)
            return c

        register_demo_agents(coord)
    else:
        coord = AgentCoordinator()
        session_factory = None
    serve(args.host, args.port, coord, token=args.token, session_factory=session_factory)


if __name__ == "__main__":
    main()
