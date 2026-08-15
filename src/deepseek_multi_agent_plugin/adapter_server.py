"""Simple HTTP adapter server for Deepseek harness integration.

Endpoint:
  POST /run  -- accepts JSON event, returns JSON result

This server uses only the Python standard library so it has no extra runtime
dependencies. The Deepseek harness can call POST /run with payload like:
  {"type": "run", "prompt": "...", "rounds": 3}

Run locally:
  python -m deepseek_multi_agent_plugin.adapter_server --port 8000 --demo

Or, when the package is installed, run:
  deepseek-plugin-runner --port 8000 --demo

The --demo flag registers two simple mock agents for testing. Replace with
real agent registrations or integrate with your agent factory.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import argparse
import logging
import threading
from typing import Tuple
from concurrent.futures import ThreadPoolExecutor

from .coordinator import AgentCoordinator, Agent, DeepseekAdapter


class AdapterHandler(BaseHTTPRequestHandler):
    def _send_json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send_json({"status": "ok"})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path != "/run":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            event = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as e:
            logging.exception("Invalid JSON")
            self._send_json({"error": "invalid json", "detail": str(e)}, code=400)
            return
        try:
            result = self.server.adapter.handle_harness_event(event)
            self._send_json(result)
        except Exception as e:
            logging.exception("Adapter error")
            self._send_json({"error": "adapter error", "detail": str(e)}, code=500)


class ThreadedHTTPServer(HTTPServer):
    daemon_threads = True


def register_demo_agents(coordinator: AgentCoordinator):
    def alpha_handler(msg):
        return f"alpha received: {msg}"

    def beta_handler(msg):
        return f"beta processed: {msg}"

    coordinator.register_agent(Agent("alpha", alpha_handler))
    coordinator.register_agent(Agent("beta", beta_handler))


def serve(host: str, port: int, coordinator: AgentCoordinator):
    server = ThreadedHTTPServer((host, port), AdapterHandler)
    server.adapter = DeepseekAdapter(coordinator)
    logging.info("Starting adapter server on %s:%s", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Shutting down adapter server")
        server.shutdown()


def main(argv: Tuple[str, ...] = None):
    parser = argparse.ArgumentParser(description="Deepseek plugin adapter HTTP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--demo", action="store_true", help="Register demo mock agents for testing")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    coord = AgentCoordinator()
    if args.demo:
        register_demo_agents(coord)

    serve(args.host, args.port, coord)


if __name__ == "__main__":
    main()
