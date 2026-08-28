"""HTTP adapter server for the DeepSeek harness.

Endpoints:

  GET  /health     -> {"status": "ok", "version": ...}
  GET  /agents     -> registered agents
  GET  /status     -> version + per-agent health counters + run count
  GET  /runs       -> recent run traces (summaries)
  GET  /runs/{id}  -> full trace (spans + tasks) of one run
  GET  /sessions   -> session statistics (also evicts expired sessions)
  POST /sessions/cleanup -> force session eviction, returns evicted ids
  DELETE /sessions/{id}  -> drop one session
  POST /run        -> {"type": "run", "prompt": "...", "strategy": "...", ...}
  POST /register   -> {"type": "register", "agents": [{name, kind, ...}]}
  GET  /history    -> recent run records (when started with --history)

Events may carry an optional ``session_id``; sessions get isolated
coordinators (own agent registry + shared memory) via SessionManager, so
concurrent harness tasks never see each other's discussion history.
Sessions are bounded by --session-ttl / --max-sessions and evicted lazily.

Access control: with no tokens configured the server runs open (local
mode). With --token, that single token gets the admin role (full access,
matching the pre-RBAC behavior). With --role ROLE:TOKEN (repeatable, or
$DS_AGENT_ROLES as JSON), each token maps to its role and endpoints
enforce minimum roles (readonly < user < operator < admin; run traces,
history and prompts need operator, registration needs admin). See
``security.py`` for the full endpoint/role matrix.

The server uses only the Python standard library. Example:

  python -m deepseek_multi_agent_plugin.adapter_server --port 8000 --demo

  curl -X POST localhost:8000/run -H "Content-Type: application/json" \\
       -d '{"type": "run", "prompt": "你好", "strategy": "debate", "rounds": 1}'
"""
import argparse
import json
import logging
import os
import re
import signal
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import parse_qs

from ..agents import AgentFactory
from ..config import build_coordinator
from ..coordinator import DEFAULT_REGISTER_KINDS, AgentCoordinator, DeepseekAdapter
from ..history import RunHistory
from ..observability import agent_health
from ..security import REQUIRED_ROLE, TokenAuthenticator
from ..sessions import SessionManager
from ..sessions import SessionRegistry as SessionRegistry  # re-exported pre-1.1 name

log = logging.getLogger("deepseek-multi-agent-plugin")
MAX_REQUEST_BYTES = 1024 * 1024


def _content_length(headers) -> int:
    """Parse and validate the ``Content-Length`` header (RFC 7230 §3.3.2).

    Rejects negative lengths (a client could otherwise force ``read(-1)``,
    which blocks the worker thread until the connection closes - a cheap
    DoS vector) and duplicate headers with conflicting values (request
    smuggling). Returns 0 when the header is absent.
    """
    values = headers.get_all("Content-Length") or []
    if not values:
        return 0
    distinct = {v.strip() for v in values}
    if len(distinct) > 1:
        raise ValueError("ambiguous Content-Length")
    try:
        length = int(distinct.pop())
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid Content-Length") from exc
    if length < 0:
        raise ValueError("invalid Content-Length")
    return length


class AdapterHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer with the DSMA-specific attributes attached by
    ``build_server``. Declared so type checkers see them."""

    daemon_threads = True
    adapter: "DeepseekAdapter"
    auth_token: Optional[str]
    authenticator: Optional[TokenAuthenticator]

_GET_ACTIONS = {
    "/health": "health",
    "/agents": "agents",
    "/status": "status",
    "/runs": "runs.list",
    "/sessions": "sessions.stats",
    "/history": "history",
}


def _get_action(path: str) -> Optional[str]:
    if path in _GET_ACTIONS:
        return _GET_ACTIONS[path]
    if path.startswith("/runs/"):
        return "runs.get"
    return None


def redact(text: str) -> str:
    """脱敏日志文本中的凭据。

    覆盖两种形态（均为正则、不依赖上下文）：
    1. ``Authorization: Bearer <token>`` 中的 token；
    2. 常见的 ``sk-`` / ``ghp-`` / ``pypi-`` 前缀 API token。
    匹配到的敏感片段统一替换为 ``***``。
    """
    text = re.sub(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1***", text)
    text = re.sub(r"\b(?:sk|ghp|pypi)-[A-Za-z0-9_-]+", "***", text)
    return text


class AdapterHandler(BaseHTTPRequestHandler):
    def version_string(self):
        """不暴露 ``Python/x.y`` / ``BaseHTTP`` 实现指纹（Server 响应头）。"""
        return "DHS-Multi-Agent"

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authenticator(self):
        auth = getattr(self.server, "authenticator", None)
        if auth is not None:
            return auth
        # ``auth_token`` 是 1.1 之前的单令牌开关：等价于一个 admin 令牌，
        # 保持旧用法（含测试与嵌入方直接给 server 赋值）继续可用。
        token = getattr(self.server, "auth_token", None)
        if not token:
            return None
        auth = TokenAuthenticator({"admin": token})
        self.server.authenticator = auth
        return auth

    def _check_access(self, action: Optional[str]) -> Optional[Tuple[dict, int]]:
        """Enforce authentication and the action's minimum role.

        Returns an (error, code) pair when the request is denied, None when
        it may proceed. Unknown actions still require a valid token when
        tokens are configured, so 401 precedes 404.
        """
        auth = self._authenticator()
        if auth is None:
            return None
        role = auth.authenticate(self.headers.get("Authorization") or "")
        if role is None:
            return ({"error": "unauthorized"}, 401)
        if action is None:
            return None
        if not auth.allows(role, action):
            log.warning("denied %s to role '%s' (requires '%s')",
                        action, role, REQUIRED_ROLE[action])
            return ({"error": "forbidden", "required_role": REQUIRED_ROLE[action]}, 403)
        return None

    def _read_event(self):
        try:
            length = _content_length(self.headers)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        if length > MAX_REQUEST_BYTES:
            raise ValueError("request body too large")
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
        path = self.path.split("?")[0]
        denied = self._check_access(_get_action(path))
        if denied:
            self._send_json(*denied)
            return
        if path == "/health":
            from .. import __version__
            out = {"status": "ok", "version": __version__}
            history = getattr(self.server.adapter, "history", None)
            if history is not None:
                out["history"] = "on"
                out["history_count"] = len(history)
            self._send_json(out)
        elif path == "/agents":
            adapter = self.server.adapter
            self._send_json({"agents": [a.describe() for a in adapter.coordinator.agents]})
        elif path == "/status":
            adapter = self.server.adapter
            coord = adapter.coordinator
            from .. import __version__
            out = {
                "status": "ok",
                "version": __version__,
                "agents": [
                    {"name": a.name, "health": agent_health(a)}
                    for a in coord.agents
                ],
                "runs": len(getattr(coord, "runs", ()) or ()),
                "sessions": len(adapter.registry) if adapter.registry is not None else 0,
            }
            self._send_json(out)
        elif path == "/runs":
            registry = getattr(self.server.adapter.coordinator, "runs", None)
            if registry is None:
                self._send_json({"runs": []})
                return
            limit = 20
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            values = parse_qs(query).get("limit")
            if values:
                try:
                    limit = min(500, max(1, int(values[0])))
                except ValueError:
                    pass
            self._send_json({"runs": registry.recent(limit)})
        elif path.startswith("/runs/"):
            run_id = path[len("/runs/"):].strip("/")
            registry = getattr(self.server.adapter.coordinator, "runs", None)
            trace = registry.get(run_id) if registry is not None else None
            if trace is None:
                self._send_json({"error": "run not found"}, code=404)
            else:
                self._send_json(trace.to_dict())
        elif path == "/sessions":
            manager = getattr(self.server.adapter, "registry", None)
            if manager is None:
                self._send_json({"count": 0, "ttl": None, "max_sessions": None,
                                 "sessions": []})
            else:
                manager.cleanup()
                self._send_json(manager.stats())
        elif path == "/history":
            history = getattr(self.server.adapter, "history", None)
            if history is None:
                self._send_json({"records": [], "enabled": False})
                return
            limit = 20
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            values = parse_qs(query).get("limit")
            if values:
                try:
                    limit = min(500, max(1, int(values[0])))
                except ValueError:
                    pass
            self._send_json({"records": history.recent(limit)})
        else:
            self._send_json({"error": "not found"}, code=404)

    def do_DELETE(self):
        path = self.path.split("?")[0]
        action = "sessions.delete" if path.startswith("/sessions/") else None
        denied = self._check_access(action)
        if denied:
            self._send_json(*denied)
            return
        if not path.startswith("/sessions/"):
            self._send_json({"error": "not found"}, code=404)
            return
        manager = getattr(self.server.adapter, "registry", None)
        session_id = path[len("/sessions/"):].strip("/")
        if manager is None or not session_id or not manager.delete(session_id):
            self._send_json({"error": "session not found"}, code=404)
        else:
            self._send_json({"deleted": session_id})

    def do_POST(self):
        path = self.path.split("?")[0]
        action = {
            "/run": "run",
            "/register": "register",
            "/sessions/cleanup": "sessions.cleanup",
        }.get(path)
        denied = self._check_access(action)
        if denied:
            self._send_json(*denied)
            return
        if path == "/sessions/cleanup":
            manager = getattr(self.server.adapter, "registry", None)
            evicted = manager.cleanup() if manager is not None else []
            self._send_json({"evicted": evicted})
            return
        if path not in ("/run", "/register"):
            self._send_json({"error": "not found"}, code=404)
            return
        # CSRF 防护：要求显式的 application/json Content-Type。跨站表单
        # （application/x-www-form-urlencoded）与 text/plain 的 simple request
        # 不触发 CORS preflight，会被此检查直接拒绝。
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != "application/json":
            self._send_json({"error": "Content-Type must be application/json"}, code=415)
            return
        try:
            length = _content_length(self.headers)
        except ValueError:
            self._send_json({"error": "invalid Content-Length"}, code=400)
            return
        if length > MAX_REQUEST_BYTES:
            self._send_json({"error": "request body too large"}, code=413)
            return
        try:
            event = self._read_event()
        except ValueError as exc:
            code = 413 if "too large" in str(exc) else 400
            self._send_json({"error": str(exc)}, code=code)
            return
        try:
            result = self.server.adapter.handle_harness_event(event)
            code = 400 if "error" in result else 200
            if result.get("error") == "too many concurrent runs":
                code = 429  # RFC 6585 语义：当前并发 run 已满
            self._send_json(result, code=code)
        except Exception as exc:
            # 记录完整异常（含 traceback），但先整体脱敏，避免凭据进入日志。
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            log.error("adapter error:\n%s", redact(tb))
            # 不把异常原文/内部提示词回给调用方，只记录到服务端日志。
            self._send_json({"error": "adapter error", "detail": "internal adapter error"}, code=500)

    def log_message(self, fmt, *args):
        log.info("%s - %s", self.address_string(), redact(fmt % args))


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
    roles: Optional[Dict[str, str]] = None,
    session_factory: Optional[Callable[[], AgentCoordinator]] = None,
    history: Optional[RunHistory] = None,
    history_prompt_limit: Optional[int] = None,
    history_final_limit: Optional[int] = None,
    session_ttl: Optional[float] = None,
    max_sessions: Optional[int] = None,
    max_concurrent_runs: int = 4,
    adapter_kwargs: Optional[Dict[str, Any]] = None,
) -> ThreadingHTTPServer:
    """Create a configured adapter server without starting it.

    Exposed separately so tests and embedders can attach an already-running
    server (e.g. to verify graceful shutdown without blocking a thread).
    ``roles`` maps role name -> token; ``token`` alone is shorthand for one
    admin token. Neither means open local mode.
    """
    server = AdapterHTTPServer((host, port), AdapterHandler)
    # Hung agent calls must not keep the container alive forever during
    # graceful shutdown; daemon threads let ``server_close`` return promptly.
    registry = (
        SessionManager(factory=session_factory, ttl=session_ttl, max_sessions=max_sessions)
        if session_factory
        else None
    )
    server.adapter = DeepseekAdapter(
        coordinator,
        registry=registry,
        history=history,
        history_prompt_limit=history_prompt_limit,
        history_final_limit=history_final_limit,
        max_concurrent_runs=max_concurrent_runs,
        **(adapter_kwargs or {}),
    )
    server.auth_token = token
    if roles:
        server.authenticator = TokenAuthenticator(roles)
    return server


def serve(
    host: str,
    port: int,
    coordinator: AgentCoordinator,
    token: Optional[str] = None,
    roles: Optional[Dict[str, str]] = None,
    session_factory: Optional[Callable[[], AgentCoordinator]] = None,
    history: Optional[RunHistory] = None,
    history_prompt_limit: Optional[int] = None,
    history_final_limit: Optional[int] = None,
    session_ttl: Optional[float] = None,
    max_sessions: Optional[int] = None,
    max_concurrent_runs: int = 4,
    adapter_kwargs: Optional[Dict[str, Any]] = None,
) -> None:
    server = build_server(
        host, port, coordinator,
        token=token,
        roles=roles,
        session_factory=session_factory,
        history=history,
        history_prompt_limit=history_prompt_limit,
        history_final_limit=history_final_limit,
        session_ttl=session_ttl,
        max_sessions=max_sessions,
        max_concurrent_runs=max_concurrent_runs,
        adapter_kwargs=adapter_kwargs,
    )
    auth = "roles" if roles else ("token" if token else "off")
    log.info("adapter server listening on http://%s:%s (agents: %s, auth: %s, sessions: %s)",
             host, port, coordinator.agent_names,
             auth,
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


def _parse_roles(pairs, env_json):
    """Merge ``--role ROLE:TOKEN`` args with $DS_AGENT_ROLES (role -> token JSON)."""
    roles: Dict[str, str] = {}
    if env_json:
        parsed = json.loads(env_json)
        if not isinstance(parsed, dict):
            raise SystemExit("$DS_AGENT_ROLES must be a JSON object of {role: token}")
        for role, token in parsed.items():
            if not isinstance(token, str) or not token.strip():
                raise SystemExit(
                    f"$DS_AGENT_ROLES role {role!r} needs a non-empty token")
        roles.update(parsed)
    for pair in pairs:
        role, sep, token = pair.partition(":")
        if not sep or not role or not token:
            raise SystemExit(f"--role expects ROLE:TOKEN, got {pair!r}")
        roles[role] = token
    return roles


def main(argv: Optional[Tuple[str, ...]] = None) -> None:
    parser = argparse.ArgumentParser(description="Deepseek multi-agent plugin HTTP adapter")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--config", default=None, help="YAML/JSON agent config file")
    parser.add_argument("--demo", action="store_true", help="register demo mock agents")
    parser.add_argument("--token", default=os.environ.get("DS_AGENT_TOKEN"),
                        help="require 'Authorization: Bearer <token>' with admin role "
                             "(default: $DS_AGENT_TOKEN)")
    parser.add_argument("--role", action="append", default=[], metavar="ROLE:TOKEN",
                        help="map a bearer token to a role (readonly/user/operator/admin); "
                             "repeatable, overrides --token")
    parser.add_argument("--history", default=os.environ.get("DS_HISTORY_FILE"),
                        help="run history JSONL file (default: $DS_HISTORY_FILE; unset = disabled)")
    parser.add_argument("--history-prompt-limit", type=int, default=None,
                        help="truncate persisted prompts to N chars (default: no truncation)")
    parser.add_argument("--history-final-limit", type=int, default=None,
                        help="truncate persisted final answers to N chars (default: no truncation)")
    parser.add_argument("--session-ttl", type=float, default=None,
                        help="evict sessions idle for more than N seconds (default: never)")
    parser.add_argument("--max-sessions", type=int, default=None,
                        help="cap the number of live sessions (least recently active evicted)")
    parser.add_argument("--max-runs", type=int,
                        default=os.environ.get("DSMA_MAX_CONCURRENT_RUNS", "4"),
                        help="cap concurrent run events (default: $DSMA_MAX_CONCURRENT_RUNS or 4)")
    parser.add_argument("--allow-register-kind", action="append", default=[],
                        metavar="KIND",
                        help="opt-in extra remotely-registrable agent kinds "
                             "(safe default set: mock|echo|deepseek|openai; "
                             "cli/http/fallback/custom need this), repeatable")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # secure-by-default remote registration (E4 audit fix): cli executes
    # local commands and http performs server-side requests - opt-in only.
    allowed_register_kinds = set(DEFAULT_REGISTER_KINDS) | set(args.allow_register_kind)
    from ..config import load_config, load_dsh_credentials
    load_dsh_credentials()  # DEEPSEEK_API_KEY from ~/.dsh/.credentials.yaml if present
    session_factory: Optional[Callable[[], AgentCoordinator]]
    if args.config:
        config = load_config(args.config)
        coord = build_coordinator(config=config)

        def session_factory() -> AgentCoordinator:
            return build_coordinator(config=dict(config))
    elif args.demo:
        coord = AgentCoordinator()

        def make_demo() -> AgentCoordinator:
            c = AgentCoordinator()
            register_demo_agents(c)
            return c

        session_factory = make_demo
        register_demo_agents(coord)
    else:
        coord = AgentCoordinator()
        session_factory = None
    history = RunHistory(args.history) if args.history else None
    roles = _parse_roles(args.role, os.environ.get("DS_AGENT_ROLES"))
    serve(args.host, args.port, coord,
          token=None if roles else args.token,
          roles=roles or None,
          session_factory=session_factory, history=history,
          history_prompt_limit=args.history_prompt_limit,
          history_final_limit=args.history_final_limit,
          session_ttl=args.session_ttl,
          max_sessions=args.max_sessions,
          max_concurrent_runs=args.max_runs,
          adapter_kwargs={"allowed_register_kinds": sorted(allowed_register_kinds)})


if __name__ == "__main__":
    main()
