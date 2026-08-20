"""Session lifecycle, memory bounds and trace capacity governance."""
import json
import threading
import urllib.error
from http.server import ThreadingHTTPServer
from urllib import request as urlreq

from deepseek_multi_agent_plugin import (
    Agent,
    AgentCoordinator,
    MessageStore,
    RunRegistry,
    SessionManager,
    Trace,
)
from deepseek_multi_agent_plugin.adapter_server import AdapterHandler, register_demo_agents
from deepseek_multi_agent_plugin.config import build_coordinator
from deepseek_multi_agent_plugin.coordinator import DeepseekAdapter


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def _factory():
    coord = AgentCoordinator()
    coord.register_agent(Agent("mock", lambda msg: f"ok: {msg}"))
    return coord


def test_sessions_are_isolated_and_reused():
    manager = SessionManager(factory=_factory)
    s1 = manager.get_or_create("s1")
    s2 = manager.get_or_create("s2")
    assert s1 is not s2
    assert manager.get_or_create("s1") is s1


def test_get_returns_existing_without_creating():
    manager = SessionManager(factory=_factory)
    assert manager.get("ghost") is None
    manager.get_or_create("s1")
    assert manager.get("s1") is not None


def test_ttl_evicts_idle_sessions():
    clock = FakeClock()
    manager = SessionManager(factory=_factory, ttl=60, clock=clock)
    manager.get_or_create("s1")
    clock.advance(30)
    manager.get_or_create("s2")  # s1 still fresh
    assert manager.session_ids() == ["s1", "s2"]
    clock.advance(61)  # both idle past ttl
    assert manager.cleanup() == ["s1", "s2"]
    assert len(manager) == 0


def test_touch_refreshes_idle_timer():
    clock = FakeClock()
    manager = SessionManager(factory=_factory, ttl=60, clock=clock)
    manager.get_or_create("s1")
    clock.advance(50)
    manager.touch("s1")
    clock.advance(50)
    assert manager.cleanup() == []
    assert manager.get("s1") is not None


def test_max_sessions_evicts_least_recently_active():
    clock = FakeClock()
    manager = SessionManager(factory=_factory, max_sessions=2, clock=clock)
    manager.get_or_create("a")
    clock.advance(1)
    manager.get_or_create("b")
    clock.advance(1)
    manager.get_or_create("c")  # over cap: "a" is least recently active
    assert manager.session_ids() == ["b", "c"]


def test_delete_removes_session():
    manager = SessionManager(factory=_factory)
    manager.get_or_create("s1")
    assert manager.delete("s1") is True
    assert manager.delete("s1") is False
    assert len(manager) == 0


def test_stats_reports_session_details():
    manager = SessionManager(factory=_factory, ttl=30, max_sessions=5)
    coord = manager.get_or_create("s1")
    coord.memory.add("user", "hello")
    stats = manager.stats()
    assert stats["count"] == 1
    assert stats["ttl"] == 30
    assert stats["max_sessions"] == 5
    assert stats["sessions"][0]["session_id"] == "s1"
    assert stats["sessions"][0]["messages"] == 1


def test_registry_alias_still_works():
    from deepseek_multi_agent_plugin.sessions import SessionRegistry
    assert SessionRegistry is SessionManager


def test_many_sessions_stay_bounded():
    clock = FakeClock()
    manager = SessionManager(factory=_factory, max_sessions=10, clock=clock)
    for i in range(100):
        manager.get_or_create(f"s{i}")
        clock.advance(0.1)
    assert len(manager) == 10


def test_message_store_capacity_bound():
    store = MessageStore(capacity=3)
    for i in range(5):
        store.add("user", f"msg {i}")
    assert [m["content"] for m in store.all()] == ["msg 2", "msg 3", "msg 4"]


def test_message_store_char_budget_drops_oldest_first():
    store = MessageStore(max_chars=10)
    store.add("user", "0123456789")  # exactly at budget
    store.add("user", "abc")
    contents = [m["content"] for m in store.all()]
    assert contents == ["0123456789", "abc"] or store.chars() <= 10 + len("abc")
    store.add("user", "defghi")
    # oldest messages dropped until within budget, newest always kept
    assert store.chars() <= 10 + len("defghi")
    assert store.all()[-1]["content"] == "defghi"


def test_message_store_keeps_newest_even_over_budget():
    store = MessageStore(max_chars=1)
    store.add("user", "tiny")
    store.add("user", "a very long message")
    assert len(store.all()) == 1
    assert store.all()[0]["content"] == "a very long message"


def test_config_memory_bounds():
    coord = build_coordinator(config={
        "coordinator": {"memory": {"capacity": 5, "max_chars": 100}},
        "agents": [{"name": "m", "kind": "mock"}],
    })
    assert coord.memory.capacity == 5
    assert coord.memory.max_chars == 100


def test_config_without_memory_section_uses_default_store():
    coord = build_coordinator(config={"agents": [{"name": "m", "kind": "mock"}]})
    assert coord.memory.capacity is None
    assert coord.memory.max_chars is None


def test_run_registry_cleanup_by_age():
    registry = RunRegistry(limit=10)
    old = Trace(prompt="old", strategy="broadcast")
    old._started_monotonic -= 3600
    recent = Trace(prompt="recent", strategy="broadcast")
    for trace in (old, recent):
        trace.finish()
        registry.record(trace)
    removed = registry.cleanup(1800)
    assert removed == 1
    assert registry.get(old.run_id) is None
    assert registry.get(recent.run_id) is not None


# ---------------------------------------------------------------- HTTP wiring
def _start_session_server(**manager_kwargs):
    server = ThreadingHTTPServer(("127.0.0.1", 0), AdapterHandler)
    coord = AgentCoordinator()
    register_demo_agents(coord)
    server.adapter = DeepseekAdapter(
        coord, registry=SessionManager(factory=_factory, **manager_kwargs)
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _request(server, method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urlreq.Request(
        f"http://127.0.0.1:{server.server_port}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urlreq.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _run_session_event(server, session_id):
    return _request(server, "POST", "/run", {
        "type": "run", "prompt": "hi", "strategy": "broadcast",
        "rounds": 1, "session_id": session_id,
    })


def test_http_sessions_endpoint_lists_sessions():
    server = _start_session_server()
    try:
        _run_session_event(server, "s1")
        stats = _request(server, "GET", "/sessions")
        assert stats["count"] == 1
        assert stats["sessions"][0]["session_id"] == "s1"
    finally:
        server.shutdown()
        server.server_close()


def test_http_delete_session():
    server = _start_session_server()
    try:
        _run_session_event(server, "s1")
        assert _request(server, "DELETE", "/sessions/s1") == {"deleted": "s1"}
        assert _request(server, "GET", "/sessions")["count"] == 0
        try:
            _request(server, "DELETE", "/sessions/s1")
            raise AssertionError("expected 404")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_http_cleanup_endpoint_respects_ttl():
    server = _start_session_server(ttl=0.0)
    try:
        _run_session_event(server, "old")
        evicted = _request(server, "POST", "/sessions/cleanup")["evicted"]
        assert evicted == ["old"]
    finally:
        server.shutdown()
        server.server_close()


def test_http_sessions_without_registry_reports_empty():
    server = ThreadingHTTPServer(("127.0.0.1", 0), AdapterHandler)
    coord = AgentCoordinator()
    register_demo_agents(coord)
    server.adapter = DeepseekAdapter(coord)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        stats = _request(server, "GET", "/sessions")
        assert stats == {"count": 0, "ttl": None, "max_sessions": None, "sessions": []}
    finally:
        server.shutdown()
        server.server_close()
