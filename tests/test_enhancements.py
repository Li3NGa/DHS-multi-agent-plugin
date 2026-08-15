"""Tests for the v0.3.0 hardening changes.

Covers: speaker labels in to_chat, retry with backoff, token usage
tracking, response_format forwarding, thread-safe registry, session
isolation via SessionRegistry/DeepseekAdapter, bearer-token auth on the
HTTP server, and non-blocking timeouts.
"""
import json
import threading
import time
from http.server import ThreadingHTTPServer
from unittest import mock
from urllib import error as urlerror
from urllib import request as urlreq

import pytest

from deepseek_multi_agent_plugin import Agent, AgentCoordinator, AgentFactory, DeepseekAdapter
from deepseek_multi_agent_plugin import agents as agents_mod
from deepseek_multi_agent_plugin import strategies as strategies_mod
from deepseek_multi_agent_plugin.adapter_server import (
    AdapterHandler,
    SessionRegistry,
    register_demo_agents,
)
from deepseek_multi_agent_plugin.memory import MessageStore


class _FakeResp:
    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


# ---------------------------------------------------------------- memory
def test_to_chat_with_speaker():
    mem = MessageStore()
    mem.add("user", "question")
    mem.add("assistant", "hello", agent="alpha")
    mem.add("assistant", "anon", agent=None)

    plain = mem.to_chat()
    assert plain[1] == {"role": "assistant", "content": "hello"}

    tagged = mem.to_chat(with_speaker=True)
    assert tagged[0] == {"role": "user", "content": "question"}
    assert tagged[1] == {"role": "assistant", "content": "[alpha]: hello"}
    assert tagged[2] == {"role": "assistant", "content": "anon"}


def test_debate_passes_speaker_labels():
    coord = AgentCoordinator()
    coord.register_agent(AgentFactory.create_agent('mock', 'a', message_template='A:{msg}'))
    coord.register_agent(AgentFactory.create_agent('mock', 'b', message_template='B:{msg}'))
    with mock.patch.object(coord.memory, "to_chat", wraps=coord.memory.to_chat) as spy:
        coord.run("hi", strategy="debate", rounds=2)
    assert any(
        kwargs.get("with_speaker") for _, kwargs in spy.call_args_list
    ), "debate should project memory with speaker labels"


# ---------------------------------------------------------------- retry
def test_retry_on_429_then_success():
    body = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
    err = urlerror.HTTPError("http://x", 429, "rate limited", None, None)
    with mock.patch.object(agents_mod.request, "urlopen",
                           side_effect=[err, _FakeResp(body)]) as m:
        out = agents_mod.chat_completion(
            base_url="https://x", api_key="k", model="m",
            messages=[], retries=1, backoff=0.01,
        )
    assert out == "ok"
    assert m.call_count == 2


def test_no_retry_on_client_error():
    err = urlerror.HTTPError("http://x", 400, "bad request", None, None)
    with mock.patch.object(agents_mod.request, "urlopen", side_effect=err) as m:
        with pytest.raises(urlerror.HTTPError):
            agents_mod.chat_completion(
                base_url="https://x", api_key="k", model="m",
                messages=[], retries=2, backoff=0.01,
            )
    assert m.call_count == 1


def test_retries_exhausted_raises():
    err = urlerror.HTTPError("http://x", 503, "unavailable", None, None)
    with mock.patch.object(agents_mod.request, "urlopen", side_effect=err) as m:
        with pytest.raises(urlerror.HTTPError):
            agents_mod.chat_completion(
                base_url="https://x", api_key="k", model="m",
                messages=[], retries=2, backoff=0.01,
            )
    assert m.call_count == 3


# ---------------------------------------------------------------- usage
def test_usage_tracking_accumulates():
    body = json.dumps({
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }).encode()
    with mock.patch.object(agents_mod.request, "urlopen", return_value=_FakeResp(body)):
        agent = AgentFactory.create_agent('deepseek', 'ds', api_key='k')
        agent.handle("q")
        agent.handle("q")
    assert agent.total_usage["prompt_tokens"] == 20
    assert agent.total_usage["total_tokens"] == 30
    assert agent.describe()["total_usage"]["total_tokens"] == 30


def test_run_meta_includes_usage():
    coord = AgentCoordinator()
    agent = AgentFactory.create_agent('mock', 'm1')
    agent.total_usage = {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}
    coord.register_agent(agent)
    result = coord.run("hi", strategy="broadcast", rounds=1)
    assert result["meta"]["usage"]["m1"]["total_tokens"] == 10


# ---------------------------------------------------------------- response_format
def test_chat_forwards_response_format():
    body = json.dumps({"choices": [{"message": {"content": "{}"}}], "usage": {}}).encode()
    with mock.patch.object(agents_mod.request, "urlopen", return_value=_FakeResp(body)) as m:
        agent = AgentFactory.create_agent('deepseek', 'ds', api_key='k')
        out = agent.chat([{"role": "user", "content": "q"}],
                         response_format={"type": "json_object"})
    assert out == "{}"
    payload = json.loads(m.call_args.args[0].data)
    assert payload["response_format"] == {"type": "json_object"}


# ---------------------------------------------------------------- registry lock
def test_registry_thread_safe():
    coord = AgentCoordinator()
    errors = []

    def register_worker(i):
        try:
            for j in range(50):
                coord.register_agent(AgentFactory.create_agent('mock', f'a{i}-{j}'))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def reader():
        try:
            for _ in range(200):
                coord.agents
                coord.agent_names
                len(coord)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=register_worker, args=(i,)) for i in range(4)]
    threads += [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(coord) == 200


# ---------------------------------------------------------------- sessions
def test_session_isolation():
    adapter = DeepseekAdapter(AgentCoordinator(), registry=SessionRegistry())

    adapter.handle_harness_event({"type": "register", "session_id": "s1",
                                  "agents": [{"name": "one", "kind": "echo"}]})
    adapter.handle_harness_event({"type": "register", "session_id": "s2",
                                  "agents": [{"name": "two", "kind": "echo"}]})

    a1 = adapter.handle_harness_event({"type": "agents", "session_id": "s1"})
    a2 = adapter.handle_harness_event({"type": "agents", "session_id": "s2"})
    assert [a["name"] for a in a1["agents"]] == ["one"]
    assert [a["name"] for a in a2["agents"]] == ["two"]

    a0 = adapter.handle_harness_event({"type": "agents"})
    assert a0["agents"] == []

    adapter.handle_harness_event({"type": "run", "session_id": "s1",
                                  "prompt": "hi", "strategy": "broadcast", "rounds": 1})
    assert len(adapter.registry.get_or_create("s1").memory) > 0
    assert len(adapter.registry.get_or_create("s2").memory) == 0


def test_session_registry_reuses_instances():
    registry = SessionRegistry()
    assert registry.get_or_create("x") is registry.get_or_create("x")
    assert registry.session_ids() == ["x"]
    assert len(registry) == 1


def test_session_registry_factory():
    calls = []

    def factory():
        calls.append(1)
        return AgentCoordinator()

    registry = SessionRegistry(factory=factory)
    registry.get_or_create("a")
    registry.get_or_create("a")
    registry.get_or_create("b")
    assert len(calls) == 2


# ---------------------------------------------------------------- auth
def _start_server(auth_token=None):
    server = ThreadingHTTPServer(("127.0.0.1", 0), AdapterHandler)
    coord = AgentCoordinator()
    register_demo_agents(coord)
    server.adapter = DeepseekAdapter(coord)
    server.auth_token = auth_token
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _request(server, path, token=None):
    headers = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    req = urlreq.Request(
        f"http://127.0.0.1:{server.server_port}{path}", headers=headers)
    with urlreq.urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode())


def test_auth_rejects_missing_token():
    server = _start_server(auth_token="secret")
    try:
        try:
            _request(server, "/health")
            raise AssertionError("expected HTTP error")
        except urlreq.HTTPError as exc:
            assert exc.code == 401
            assert json.loads(exc.read().decode()) == {"error": "unauthorized"}
    finally:
        server.shutdown()
        server.server_close()


def test_auth_accepts_valid_token():
    server = _start_server(auth_token="secret")
    try:
        status, body = _request(server, "/health", token="secret")
        assert status == 200
        assert body == {"status": "ok"}
    finally:
        server.shutdown()
        server.server_close()


def test_auth_rejects_wrong_token():
    server = _start_server(auth_token="secret")
    try:
        try:
            _request(server, "/health", token="wrong")
            raise AssertionError("expected HTTP error")
        except urlreq.HTTPError as exc:
            assert exc.code == 401
    finally:
        server.shutdown()
        server.server_close()


def test_no_auth_by_default():
    server = _start_server()
    try:
        status, body = _request(server, "/health")
        assert status == 200
        assert body == {"status": "ok"}
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------- timeouts
def test_timeout_does_not_block_on_slow_agent():
    def slow_handler(msg):
        time.sleep(1.5)
        return "late"

    agent = Agent("slow", slow_handler)
    start = time.monotonic()
    out = strategies_mod._call_agent(agent, "x", timeout=0.2)
    elapsed = time.monotonic() - start
    assert isinstance(out, dict) and "error" in out
    assert elapsed < 1.0, f"_call_agent blocked for {elapsed:.2f}s despite timeout"


def test_parallel_timeout_does_not_block():
    coord = AgentCoordinator()
    coord.register_agent(Agent("slow", lambda msg: (time.sleep(1.5), "late")[1]))
    coord.register_agent(AgentFactory.create_agent('echo', 'fast'))
    start = time.monotonic()
    results = strategies_mod._parallel(coord, "x", timeout=0.2)
    elapsed = time.monotonic() - start
    assert "error" in results["slow"]
    assert results["fast"] == "fast echo: x"
    assert elapsed < 1.0, f"_parallel blocked for {elapsed:.2f}s despite timeout"
