"""FallbackAgent：后端链式接管（provider / agent 级容错）。"""
import pytest

from deepseek_multi_agent_plugin import Agent, AgentCoordinator, AgentFactory, FallbackAgent
from deepseek_multi_agent_plugin.exceptions import AgentError, BudgetExceeded


def _usage_agent(name, reply, tokens=0):
    """handler agent，调用时把 token 用量记到自己头上（模拟 LLM 计量）。"""
    holder = {}

    def handler(msg):
        if tokens:
            holder["agent"]._add_usage(
                {"prompt_tokens": tokens, "total_tokens": tokens}
            )
        if isinstance(reply, Exception):
            raise reply
        return reply

    agent = Agent(name, handler)
    holder["agent"] = agent
    return agent


def test_first_backend_answers():
    fa = FallbackAgent("f", [_usage_agent("primary", "primary-answer"),
                             _usage_agent("backup", "backup-answer")])
    assert fa.handle("hi") == "primary-answer"


def test_failing_backend_hands_over():
    fa = FallbackAgent("f", [_usage_agent("primary", RuntimeError("boom")),
                             _usage_agent("backup", "backup-answer")])
    assert fa.handle("hi") == "backup-answer"


def test_error_dict_backend_hands_over():
    fa = FallbackAgent("f", [_usage_agent("primary", {"error": "timeout"}),
                             _usage_agent("backup", "ok")])
    assert fa.handle("hi") == "ok"


def test_all_backends_failing_raises_agent_error():
    fa = FallbackAgent("f", [_usage_agent("a", ValueError("first")),
                             _usage_agent("b", ValueError("second"))])
    with pytest.raises(AgentError, match="second"):
        fa.handle("hi")


def test_usage_of_winning_backend_is_aggregated():
    fa = FallbackAgent("f", [_usage_agent("primary", RuntimeError("boom")),
                             _usage_agent("backup", "ok", tokens=17)])
    fa.handle("hi")
    assert fa.total_usage["total_tokens"] == 17
    assert fa.total_usage["prompt_tokens"] == 17


def test_budget_exceeded_is_not_swallowed():
    def handler(msg):
        raise BudgetExceeded("call budget exhausted")

    fa = FallbackAgent("f", [Agent("primary", handler),
                             _usage_agent("backup", "should-not-run")])
    with pytest.raises(BudgetExceeded):
        fa.handle("hi")


def test_capabilities_are_the_union_of_backends():
    fa = FallbackAgent("f", [Agent("a", capabilities="research"),
                             Agent("b", capabilities="coding,analysis")])
    assert fa.capabilities == frozenset({"research", "coding", "analysis"})


def test_describe_lists_backends():
    fa = FallbackAgent("f", [Agent("a"), Agent("b")])
    assert fa.describe()["backends"] == ["a", "b"]


def test_factory_builds_fallback_and_validates_backends():
    primary, backup = Agent("a"), Agent("b")
    fa = AgentFactory.create_agent("fallback", "f", backends=[primary, backup])
    assert isinstance(fa, FallbackAgent)
    with pytest.raises(ValueError, match="backends"):
        AgentFactory.create_agent("fallback", "f", backends=[])


def test_fallback_agent_inside_a_coordinator_run():
    coord = AgentCoordinator()
    coord.register_agent(FallbackAgent(
        "worker", [_usage_agent("primary", RuntimeError("provider down")),
                   _usage_agent("backup", "recovered")]
    ))
    out = coord.run("hello", strategy="broadcast", rounds=1)
    assert "recovered" in out["final"]


def test_fallback_agent_error_dict_in_run():
    """run 内后端全部失败时，按普通 agent 错误记录，不炸掉整轮。"""
    coord = AgentCoordinator()
    coord.register_agent(Agent("healthy", lambda msg: "fine"))
    coord.register_agent(FallbackAgent(
        "broken", [_usage_agent("a", ValueError("x")),
                   _usage_agent("b", ValueError("y"))]
    ))
    out = coord.run("hello", strategy="broadcast", rounds=1)
    assert "fine" in out["final"]
    assert "all 2 backends failed" in str(out["rounds"][0]["responses"]["broken"])
