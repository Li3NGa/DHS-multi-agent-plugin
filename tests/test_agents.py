"""Tests for Agent and AgentFactory."""
import json
import threading
import urllib.error
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import pytest

from deepseek_multi_agent_plugin import Agent, AgentFactory
from deepseek_multi_agent_plugin import agents as agents_mod


def test_mock_agent_from_factory():
    a = AgentFactory.create_agent('mock', 'm1', message_template='hello {msg} from {name}')
    assert a.handle('world') == 'hello world from m1'


def test_echo_agent():
    a = AgentFactory.create_agent('echo', 'e1')
    assert a.handle('ping') == 'e1 echo: ping'


def test_custom_agent():
    def upcase(msg):
        return str(msg).upper()

    a = AgentFactory.create_agent('custom', 'c1', handler=upcase)
    assert a.handle('hi') == 'HI'


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        AgentFactory.create_agent('bogus', 'x')


def test_unknown_provider_raises():
    with pytest.raises(ValueError):
        Agent('x', provider='bogus')


def test_agent_without_backend_raises():
    a = Agent('x')
    with pytest.raises(RuntimeError):
        a.handle("hi")


def test_from_config_defaults_to_mock():
    a = AgentFactory.from_config({"name": "a1", "message_template": "tpl {msg}"})
    assert a.handle('m') == 'tpl m'


def test_describe():
    a = AgentFactory.create_agent('mock', 'd1', role='r')
    info = a.describe()
    assert info["name"] == "d1"
    assert info["role"] == "r"


class _FakeResp:
    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def test_deepseek_provider_calls_chat_completions():
    body = json.dumps({"choices": [{"message": {"content": "hello from deepseek"}}]}).encode()
    with mock.patch.object(agents_mod.request, "urlopen", return_value=_FakeResp(body)) as m:
        agent = AgentFactory.create_agent('deepseek', 'ds', api_key='test-key')
        out = agent.handle("hi", context=[{"role": "assistant", "content": "prev"}])
    assert out == "hello from deepseek"
    req = m.call_args.args[0]
    payload = json.loads(req.data)
    assert payload["model"] == "deepseek-chat"
    assert payload["messages"][-1] == {"role": "user", "content": "hi"}
    assert payload["messages"][-2] == {"role": "assistant", "content": "prev"}
    assert req.headers["Authorization"] == "Bearer test-key"
    assert req.headers["Content-type"] == "application/json"


def test_openai_provider_uses_env_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    body = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
    with mock.patch.object(agents_mod.request, "urlopen", return_value=_FakeResp(body)) as m:
        agent = AgentFactory.create_agent('openai', 'oa')
        agent.handle("q")
    req = m.call_args.args[0]
    assert req.headers["Authorization"] == "Bearer env-key"
    assert req.full_url.endswith("/v1/chat/completions")


def test_deepseek_provider_missing_key_raises(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    agent = AgentFactory.create_agent('deepseek', 'ds')
    with pytest.raises(RuntimeError):
        agent.handle("q")


def _http_error(code, headers=None):
    msg = Message()
    for key, value in (headers or {}).items():
        msg[key] = value
    return urllib.error.HTTPError(
        "http://example.invalid/chat/completions", code, "error", msg, None
    )


def test_chat_completion_respects_retry_after(monkeypatch):
    body = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        if len(calls) == 1:
            raise _http_error(429, {"Retry-After": "2"})
        return _FakeResp(body)

    sleeps = []
    monkeypatch.setattr(agents_mod.time, "sleep", sleeps.append)
    monkeypatch.setattr(agents_mod.request, "urlopen", fake_urlopen)
    out = agents_mod.chat_completion(
        "http://x", "k", "m", [{"role": "user", "content": "q"}],
        retries=1, backoff=0.5,
    )
    assert out == "ok"
    assert len(calls) == 2
    assert sleeps == [2.0]  # Retry-After wins over exponential backoff


def test_chat_completion_retries_on_bad_json(monkeypatch):
    body = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        if len(calls) == 1:
            return _FakeResp(b"not json")
        return _FakeResp(body)

    monkeypatch.setattr(agents_mod.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(agents_mod.request, "urlopen", fake_urlopen)
    out = agents_mod.chat_completion(
        "http://x", "k", "m", [{"role": "user", "content": "q"}],
        retries=1, backoff=0.0,
    )
    assert out == "ok"
    assert len(calls) == 2


class _EchoHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        payload = json.loads(raw.decode())
        body = json.dumps({"echo": payload.get("message")}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def test_http_agent():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EchoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        agent = AgentFactory.create_agent('http', 'h1',
                                         url=f"http://127.0.0.1:{server.server_port}/")
        out = agent.handle("ping")
        assert out == {"echo": "ping"}
    finally:
        server.shutdown()
        server.server_close()
