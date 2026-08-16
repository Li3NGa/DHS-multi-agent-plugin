"""LLM 响应缓存测试（ResponseCache / chat_completion / Agent.cache，v0.5.0）。"""
import json
from unittest import mock

from deepseek_multi_agent_plugin import AgentFactory, ResponseCache, chat_completion
from deepseek_multi_agent_plugin import agents as agents_mod


class _FakeResp:
    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def _body(content="cached-answer", usage=None):
    return json.dumps(
        {"choices": [{"message": {"content": content}}], "usage": usage or {}}
    ).encode()


# ---------------------------------------------------------------- ResponseCache
def test_response_cache_lru_eviction():
    cache = ResponseCache(maxsize=2)
    cache.put("a", "1")
    cache.put("b", "2")
    assert cache.get("a") == "1"  # a 变为最近使用
    cache.put("c", "3")  # 淘汰最久未使用的 b
    assert cache.get("b") is None
    assert cache.get("a") == "1"
    assert cache.get("c") == "3"
    assert len(cache) == 2


def test_response_cache_maxsize_min_one():
    cache = ResponseCache(maxsize=0)
    cache.put("a", "1")
    cache.put("b", "2")
    assert len(cache) == 1
    assert cache.get("a") is None


def test_response_cache_clear():
    cache = ResponseCache()
    cache.put("a", "1")
    cache.clear()
    assert len(cache) == 0
    assert cache.get("a") is None


# ---------------------------------------------------------------- chat_completion
def test_chat_completion_cache_hit_does_not_hit_http():
    cache = ResponseCache()
    with mock.patch.object(
        agents_mod.request, "urlopen", return_value=_FakeResp(_body())
    ) as urlopen:
        first = chat_completion(
            "https://x", "k", "m", [{"role": "user", "content": "q"}],
            return_usage=True, cache=cache,
        )
        second = chat_completion(
            "https://x", "k", "m", [{"role": "user", "content": "q"}],
            return_usage=True, cache=cache,
        )
    assert urlopen.call_count == 1
    assert first["content"] == "cached-answer"
    assert first["usage"].get("cache_hit") is None
    assert second["content"] == "cached-answer"
    assert second["usage"]["cache_hit"] is True
    assert second["usage"]["total_tokens"] == 0


def test_chat_completion_cache_key_includes_messages():
    cache = ResponseCache()
    with mock.patch.object(
        agents_mod.request, "urlopen", return_value=_FakeResp(_body())
    ) as urlopen:
        chat_completion(
            "https://x", "k", "m", [{"role": "user", "content": "q1"}], cache=cache,
        )
        chat_completion(
            "https://x", "k", "m", [{"role": "user", "content": "q2"}], cache=cache,
        )
    assert urlopen.call_count == 2


def test_chat_completion_without_cache_never_hits():
    with mock.patch.object(
        agents_mod.request, "urlopen", return_value=_FakeResp(_body())
    ) as urlopen:
        chat_completion("https://x", "k", "m", [{"role": "user", "content": "q"}])
        chat_completion("https://x", "k", "m", [{"role": "user", "content": "q"}])
    assert urlopen.call_count == 2


# ---------------------------------------------------------------- Agent.cache
def test_agent_cache_enabled_counts_hits():
    body = _body(
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    )
    with mock.patch.object(
        agents_mod.request, "urlopen", return_value=_FakeResp(body)
    ) as urlopen:
        agent = AgentFactory.create_agent('deepseek', 'ds', api_key='k', cache=True)
        agent.handle("q")
        agent.handle("q")
    assert urlopen.call_count == 1
    assert agent.cache_hits == 1
    assert agent.total_usage["prompt_tokens"] == 10
    assert agent.total_usage["total_tokens"] == 15
    assert agent.describe()["cache"] is True
    assert agent.describe()["cache_hits"] == 1


def test_agent_cache_disabled_by_default():
    agent = AgentFactory.create_agent('deepseek', 'ds', api_key='k')
    assert agent.cache is False
    assert agent._cache is None
    assert agent.cache_hits == 0


def test_agent_factory_config_cache_passthrough():
    agent = AgentFactory.from_config(
        {"name": "ds", "kind": "deepseek", "api_key": "k", "cache": True}
    )
    assert agent.cache is True
    assert agent._cache is not None


def test_mock_agent_does_not_participate_in_cache():
    agent = AgentFactory.create_agent('mock', 'm', cache=True)
    assert agent.cache is False
    assert agent._cache is None


def test_agent_retries_configurable():
    assert AgentFactory.create_agent('deepseek', 'd1', api_key='k', retries=5).retries == 5
    assert AgentFactory.from_config(
        {"name": "d2", "kind": "deepseek", "api_key": "k", "retries": 3}
    ).retries == 3
    assert AgentFactory.create_agent('deepseek', 'd3', api_key='k').retries == 2
