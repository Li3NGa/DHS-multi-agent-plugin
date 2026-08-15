"""Tests for AgentCoordinator."""
import time

import pytest

from deepseek_multi_agent_plugin import Agent, AgentCoordinator, AgentFactory


def _team(names=("researcher", "critic")):
    coord = AgentCoordinator()
    for n in names:
        coord.register_agent(
            AgentFactory.create_agent("mock", n, message_template="[{name}] {msg}")
        )
    return coord


def test_register_and_unregister():
    coord = _team()
    assert coord.agent_names == ["researcher", "critic"]
    coord.unregister_agent("critic")
    assert coord.agent_names == ["researcher"]
    assert coord.get_agent("critic") is None


def test_register_duplicate_without_replace_raises():
    coord = _team(["a"])
    other = AgentFactory.create_agent("mock", "a")
    with pytest.raises(ValueError):
        coord.register_agent(other, replace=False)


def test_run_without_agents_raises():
    coord = AgentCoordinator()
    with pytest.raises(RuntimeError):
        coord.run("hi")


def test_run_broadcast():
    coord = _team()
    result = coord.run("hello", strategy="broadcast", rounds=1)
    assert result["strategy"] == "broadcast"
    assert len(result["rounds"]) == 1
    assert "researcher" in result["final"]
    assert "critic" in result["final"]
    assert result["meta"]["agents"] == ["researcher", "critic"]


def test_unknown_strategy_raises():
    coord = _team()
    with pytest.raises(ValueError):
        coord.run("hello", strategy="nope")


def test_auto_strategy_single_agent_broadcast():
    coord = _team(["solo"])
    result = coord.run("hello")
    assert result["strategy"] == "broadcast"


def test_auto_strategy_with_supervisor():
    coord = _team(["supervisor", "worker"])
    result = coord.run("hello")
    assert result["strategy"] == "supervisor"


def test_auto_strategy_two_agents_debate():
    coord = _team(["a", "b"])
    result = coord.run("hello", rounds=1)
    assert result["strategy"] == "debate"


def test_memory_records_discussion():
    coord = _team()
    coord.run("hello", strategy="broadcast", rounds=1)
    roles = [m["role"] for m in coord.memory.all()]
    assert "user" in roles
    assert roles.count("assistant") == 2


def test_slow_agent_is_captured_as_error():
    coord = AgentCoordinator(timeout=5.0)

    def slow(msg):
        time.sleep(1.0)
        return "slow done"

    coord.register_agent(Agent("slow", slow))
    coord.register_agent(AgentFactory.create_agent("mock", "fast", message_template="ok {msg}"))
    result = coord.run("hello", strategy="broadcast", rounds=1, timeout=0.2)
    responses = result["rounds"][0]["responses"]
    assert "fast" in responses
    assert responses["slow"] == {"error": "timeout"}


def test_agent_exception_is_captured():
    coord = AgentCoordinator()

    def boom(msg):
        raise RuntimeError("kaboom")

    coord.register_agent(Agent("boom", boom))
    result = coord.run("hello", strategy="broadcast", rounds=1)
    assert "kaboom" in str(result["rounds"][0]["responses"]["boom"])


def test_legacy_run_cooperative_task():
    coord = _team()
    history = coord.run_cooperative_task("hello", rounds=1)
    assert isinstance(history, list)
    assert history[0]["round"] == 1


def test_legacy_broadcast():
    coord = _team()
    responses = coord.broadcast("hello")
    assert set(responses) == {"researcher", "critic"}
