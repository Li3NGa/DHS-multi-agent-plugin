"""Tests for the relay (pass-the-baton draft refinement) strategy."""
import pytest

from deepseek_multi_agent_plugin import Agent, AgentCoordinator


def _draft(message) -> str:
    """Extract the current draft section from a relay prompt."""
    text = str(message)
    return text.split("当前草稿：\n", 1)[1].split("\n\n要求：", 1)[0]


def test_relay_passes_draft_along():
    coord = AgentCoordinator()
    coord.register_agent(Agent("drafter", lambda msg: _draft(msg) + "->A"))
    coord.register_agent(Agent("polisher", lambda msg: _draft(msg) + "->B"))
    coord.register_agent(Agent("reviewer", lambda msg: _draft(msg) + "->C"))
    result = coord.run("写一段产品介绍", strategy="relay", rounds=1)
    steps = result["rounds"][0]["steps"]
    assert [s["agent"] for s in steps] == ["drafter", "polisher", "reviewer"]
    assert steps[0]["response"] == "写一段产品介绍->A"
    assert steps[1]["response"] == "写一段产品介绍->A->B"
    assert steps[2]["response"] == "写一段产品介绍->A->B->C"
    assert result["final"] == "写一段产品介绍->A->B->C"
    assert result["rounds"][0]["converged"] is False


def test_relay_converges_when_draft_unchanged():
    coord = AgentCoordinator()
    coord.register_agent(Agent("a", lambda msg: _draft(msg)))
    coord.register_agent(Agent("b", lambda msg: _draft(msg)))
    result = coord.run("草稿v1", strategy="relay", rounds=5)
    assert len(result["rounds"]) == 1
    assert result["rounds"][0]["converged"] is True
    assert result["final"] == "草稿v1"


def test_relay_stops_after_two_flat_rounds():
    calls = {"n": 0}

    def once_then_flat(msg):
        if calls["n"] == 0:
            calls["n"] += 1
            return _draft(msg) + "-once"
        return _draft(msg)

    coord = AgentCoordinator()
    coord.register_agent(Agent("a", once_then_flat))
    coord.register_agent(Agent("b", lambda msg: _draft(msg)))
    result = coord.run("t", strategy="relay", rounds=5)
    assert len(result["rounds"]) == 2
    assert result["rounds"][0]["converged"] is False
    assert result["rounds"][1]["converged"] is True
    assert result["final"] == "t-once"


def test_relay_skips_failing_agent():
    def boom(msg):
        raise RuntimeError("boom")

    coord = AgentCoordinator()
    coord.register_agent(Agent("bad", boom))
    coord.register_agent(Agent("good", lambda msg: _draft(msg) + "+fixed"))
    result = coord.run("draft", strategy="relay", rounds=1)
    steps = result["rounds"][0]["steps"]
    assert "error" in steps[0]["response"]
    assert steps[1]["response"] == "draft+fixed"
    assert result["final"] == "draft+fixed"


def test_relay_needs_two_agents():
    coord = AgentCoordinator()
    coord.register_agent(Agent("solo", lambda msg: msg))
    with pytest.raises(ValueError):
        coord.run("hi", strategy="relay")


def test_relay_uses_order():
    coord = AgentCoordinator()
    coord.register_agent(Agent("a", lambda msg: _draft(msg) + ">A"))
    coord.register_agent(Agent("b", lambda msg: _draft(msg) + ">B"))
    result = coord.run("t", strategy="relay", order=["b", "a"], rounds=1)
    assert [s["agent"] for s in result["rounds"][0]["steps"]] == ["b", "a"]
    assert result["final"] == "t>B>A"


def test_relay_unknown_order_raises():
    coord = AgentCoordinator()
    coord.register_agent(Agent("a", lambda msg: _draft(msg)))
    coord.register_agent(Agent("b", lambda msg: _draft(msg)))
    with pytest.raises(ValueError):
        coord.run("t", strategy="relay", order=["ghost"])
