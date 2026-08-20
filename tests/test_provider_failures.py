"""Provider 失败注入（5xx / 连接错误 / 畸形响应）与并发压力测试。"""
import json
import threading
import urllib.error
from email.message import Message

import pytest

from deepseek_multi_agent_plugin import Agent, AgentCoordinator, AgentFactory
from deepseek_multi_agent_plugin import agents as agents_mod
from deepseek_multi_agent_plugin.runtime.executor import DEFAULT_MAX_WORKERS
from deepseek_multi_agent_plugin.sessions import SessionManager


class _FakeResp:
    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def _ok_body(content="ok"):
    return json.dumps({"choices": [{"message": {"content": content}}],
                       "usage": {"total_tokens": 3}}).encode()


def _http_error(code, headers=None):
    msg = Message()
    for key, value in (headers or {}).items():
        msg[key] = value
    return urllib.error.HTTPError(
        "http://example.invalid/chat/completions", code, "error", msg, None
    )


def _flaky(errors, content="ok", monkeypatch=None):
    """前 len(errors) 次调用抛出给定异常，之后返回正常响应。"""
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        if len(calls) <= len(errors):
            raise errors[len(calls) - 1]
        return _FakeResp(_ok_body(content))

    return fake_urlopen, calls


# ------------------------------------------------------------- HTTP 状态码
def test_server_error_500_is_retried_then_succeeds(monkeypatch):
    fake, calls = _flaky([_http_error(500)])
    sleeps = []
    monkeypatch.setattr(agents_mod.time, "sleep", sleeps.append)
    monkeypatch.setattr(agents_mod.request, "urlopen", fake)
    out = agents_mod.chat_completion(
        "http://x", "k", "m", [{"role": "user", "content": "q"}],
        retries=2, backoff=0.5,
    )
    assert out == "ok"
    assert len(calls) == 2
    assert len(sleeps) == 1


def test_all_retryable_statuses_are_retried(monkeypatch):
    for code in (429, 500, 502, 503, 504):
        fake, calls = _flaky([_http_error(code)])
        monkeypatch.setattr(agents_mod.time, "sleep", lambda *_: None)
        monkeypatch.setattr(agents_mod.request, "urlopen", fake)
        out = agents_mod.chat_completion(
            "http://x", "k", "m", [{"role": "user", "content": "q"}], retries=1,
        )
        assert out == "ok"
        assert len(calls) == 2, f"status {code} should be retried"


def test_non_retryable_status_is_not_retried(monkeypatch):
    fake, calls = _flaky([_http_error(400)])
    sleeps = []
    monkeypatch.setattr(agents_mod.time, "sleep", sleeps.append)
    monkeypatch.setattr(agents_mod.request, "urlopen", fake)
    with pytest.raises(urllib.error.HTTPError):
        agents_mod.chat_completion(
            "http://x", "k", "m", [{"role": "user", "content": "q"}], retries=3,
        )
    assert len(calls) == 1
    assert sleeps == []


def test_retries_exhausted_raises_and_run_records_error(monkeypatch):
    fake, calls = _flaky([_http_error(503), _http_error(503), _http_error(503)])
    monkeypatch.setattr(agents_mod.time, "sleep", lambda *_: None)
    monkeypatch.setattr(agents_mod.request, "urlopen", fake)
    agent = AgentFactory.create_agent("deepseek", "ds", api_key="k", retries=2)
    with pytest.raises(urllib.error.HTTPError):
        agent.handle("q")
    assert len(calls) == 3  # 初次 + 2 次重试

    # run 内部按 error dict 记录，不炸掉整轮
    coord = AgentCoordinator()
    coord.register_agent(agent)
    coord.register_agent(Agent("healthy", lambda msg: "fine"))
    out = coord.run("q", strategy="broadcast", rounds=1)
    assert "fine" in out["final"]


# ------------------------------------------------------------- 连接层错误
def test_connection_reset_is_retried(monkeypatch):
    fake, calls = _flaky([ConnectionResetError("reset by peer")])
    monkeypatch.setattr(agents_mod.time, "sleep", lambda *_: None)
    monkeypatch.setattr(agents_mod.request, "urlopen", fake)
    out = agents_mod.chat_completion(
        "http://x", "k", "m", [{"role": "user", "content": "q"}], retries=1,
    )
    assert out == "ok"
    assert len(calls) == 2


def test_persistent_connection_error_surfaces_in_run(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(agents_mod.time, "sleep", lambda *_: None)
    monkeypatch.setattr(agents_mod.request, "urlopen", fake_urlopen)
    agent = AgentFactory.create_agent("deepseek", "ds", api_key="k", retries=0)
    coord = AgentCoordinator()
    coord.register_agent(agent)
    out = coord.run("q", strategy="broadcast", rounds=1)
    assert "connection refused" in out["rounds"][0]["responses"]["ds"]["error"]


# ------------------------------------------------------------- 畸形响应
def test_malformed_body_raises_with_no_retries(monkeypatch):
    monkeypatch.setattr(agents_mod.request, "urlopen",
                        lambda req, timeout=None: _FakeResp(b"<html>gateway</html>"))
    with pytest.raises(ValueError):
        agents_mod.chat_completion(
            "http://x", "k", "m", [{"role": "user", "content": "q"}], retries=0,
        )


def test_malformed_body_is_retried(monkeypatch):
    calls = []

    def flaky(req, timeout=None):
        calls.append(req)
        if len(calls) == 1:
            return _FakeResp(b"not json")
        return _FakeResp(_ok_body())

    monkeypatch.setattr(agents_mod.time, "sleep", lambda *_: None)
    monkeypatch.setattr(agents_mod.request, "urlopen", flaky)
    out = agents_mod.chat_completion(
        "http://x", "k", "m", [{"role": "user", "content": "q"}], retries=1,
    )
    assert out == "ok"
    assert len(calls) == 2


def test_json_without_choices_is_returned_verbatim(monkeypatch):
    monkeypatch.setattr(
        agents_mod.request, "urlopen",
        lambda req, timeout=None: _FakeResp(b'{"error": {"message": "quota"}}'),
    )
    out = agents_mod.chat_completion(
        "http://x", "k", "m", [{"role": "user", "content": "q"}], retries=0,
    )
    assert "quota" in out


# ------------------------------------------------------------- 压力测试
def test_100_concurrent_sessions_10_agents_stress():
    """100 个并发会话、10 个 agent：会话隔离 + 共享池不失控。"""
    def factory():
        coord = AgentCoordinator()
        for i in range(10):
            coord.register_agent(
                AgentFactory.create_agent("mock", f"a{i}", message_template=f"a{i}: {{msg}}")
            )
        return coord

    manager = SessionManager(factory=factory, max_sessions=100)
    errors = []

    def worker(i):
        try:
            coord = manager.get_or_create(f"s{i}")
            out = coord.run(f"msg-{i}", strategy="broadcast", rounds=1)
            final = out["final"]
            # 10 个 agent 各自应答一次本会话的 prompt，不能混入别的会话
            if final.count(f"msg-{i}") != 10 or final.count("msg-") != 10:
                errors.append(f"session {i} saw foreign memory: {final!r}")
        except Exception as exc:  # noqa: BLE001 - 收集全部线程错误
            errors.append(f"session {i}: {exc}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors
    stats = manager.stats()
    assert stats["count"] == 100
    assert len({s["session_id"] for s in stats["sessions"]}) == 100


def test_concurrent_runs_share_one_bounded_executor():
    """10 个并发 run、每 run 10 个 agent：全部完成且线程数有上限。"""
    coord = AgentCoordinator()
    for i in range(10):
        coord.register_agent(AgentFactory.create_agent("mock", f"m{i}"))

    results = {}
    errors = []

    def worker(i):
        try:
            out = coord.run(f"p{i}", strategy="broadcast", rounds=1)
            results[i] = out["final"]
        except Exception as exc:  # noqa: BLE001 - 收集全部线程错误
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors
    assert len(results) == 10
    # 每个并发 run 只看到自己的 prompt
    for i, final in results.items():
        assert f"p{i}" in final
    active = threading.active_count()
    assert active <= DEFAULT_MAX_WORKERS + 20, active


def test_mixed_failures_under_concurrency():
    """并发 run 中部分 agent 持续失败：错误隔离，健康 agent 照常返回。"""

    def flaky(i):
        def handler(msg):
            if i % 2 == 0:
                raise RuntimeError(f"agent {i} down")
            return f"ok-{i}: {msg}"

        return Agent(f"m{i}", handler)

    coord = AgentCoordinator()
    for i in range(6):
        coord.register_agent(flaky(i))

    errors = []
    outputs = []

    def worker(i):
        try:
            outputs.append(coord.run(f"q{i}", strategy="broadcast", rounds=1))
        except Exception as exc:  # noqa: BLE001 - 收集全部线程错误
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors
    for out in outputs:
        responses = out["rounds"][0]["responses"]
        broken = {k for k, v in responses.items() if isinstance(v, dict) and "error" in v}
        assert broken == {"m0", "m2", "m4"}
        assert all("ok-" in v for k, v in responses.items() if k not in broken)
