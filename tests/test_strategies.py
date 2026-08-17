"""Tests for the collaboration strategies."""
import pytest

from deepseek_multi_agent_plugin import Agent, AgentCoordinator, AgentFactory
from deepseek_multi_agent_plugin.strategies import _parse_vote


def _team(agents=("researcher", "critic")):
    coord = AgentCoordinator()
    for name in agents:
        coord.register_agent(
            AgentFactory.create_agent("mock", name, message_template="[{name}] {msg}")
        )
    return coord


def test_broadcast_rounds_feed_back():
    coord = _team()
    result = coord.run("hello", strategy="broadcast", rounds=2)
    assert len(result["rounds"]) == 2
    first = result["rounds"][0]["responses"]
    second = result["rounds"][1]["responses"]
    # round 2 input contains round 1 outputs
    assert "[researcher]" in str(second["critic"]) or "[critic]" in str(second["researcher"])
    assert first["researcher"].startswith("[researcher]")


def test_sequential_uses_order():
    coord = _team()
    result = coord.run("hello", strategy="sequential", order=["critic", "researcher"])
    steps = [rec["agent"] for rec in result["rounds"]]
    assert steps == ["critic", "researcher"]
    assert result["final"].startswith("[researcher]")
    # critic saw only the prompt, researcher saw critic output too
    assert "critic" in result["rounds"][1]["response"]


def test_sequential_unknown_order_raises():
    coord = _team()
    with pytest.raises(ValueError):
        coord.run("hello", strategy="sequential", order=["ghost"])


def test_debate_with_judge():
    coord = _team()
    judge = AgentFactory.create_agent("mock", "judge", message_template="裁定: {msg}")
    coord.register_agent(judge)
    result = coord.run("hello", strategy="debate", rounds=2, judge="judge")
    kinds = [rec.get("kind") for rec in result["rounds"]]
    assert kinds.count("debate") == 2
    assert kinds[-1] is None and result["rounds"][-1]["step"] == "judge"
    assert result["final"].startswith("裁定:")
    assert result["rounds"][-1]["agent"] == "judge"


def test_debate_needs_two_agents():
    coord = _team(["only"])
    with pytest.raises(ValueError):
        coord.run("hello", strategy="debate", rounds=1)


def test_supervisor_decomposes_and_reports():
    coord = AgentCoordinator()

    def plan_handler(msg):
        return "子任务一\n子任务二\n子任务三"

    def worker_handler(msg):
        return f"完成: {msg}"

    coord.register_agent(Agent("supervisor", plan_handler))
    coord.register_agent(Agent("w1", worker_handler))
    coord.register_agent(Agent("w2", worker_handler))
    result = coord.run("build something", strategy="supervisor", timeout=5)
    records = {rec["step"]: rec for rec in result["rounds"]}
    assert "plan" in records
    assert records["plan"]["response"] == "子任务一\n子任务二\n子任务三"
    work = records["work"]
    assert work["subtasks"] == ["子任务一", "子任务二", "子任务三"]
    assert set(work["assigned"]) == {"w1", "w2"}
    assert "完成:" in work["results"]["w1"]
    assert str(result["final"]) == "子任务一\n子任务二\n子任务三"


def test_supervisor_without_workers_raises():
    coord = _team(["solo"])
    with pytest.raises(ValueError):
        coord.run("hello", strategy="supervisor")


def test_consensus_majority_wins():
    coord = AgentCoordinator()
    coord.register_agent(Agent(
        "proposer_a", lambda msg: "ANSWER-A" if "候选方案" not in str(msg) else "vote: proposer_a"))
    coord.register_agent(Agent(
        "proposer_b", lambda msg: "ANSWER-B" if "候选方案" not in str(msg) else "vote: proposer_b"))
    coord.register_agent(Agent("voter", lambda msg: "vote: proposer_a"))
    result = coord.run("pick best", strategy="consensus")
    steps = {rec["step"]: rec for rec in result["rounds"]}
    assert steps["propose"]["responses"]["proposer_a"] == "ANSWER-A"
    assert steps["final"]["winner"] == "proposer_a"
    assert result["final"] == "ANSWER-A"
    assert steps["final"]["votes"] == {"proposer_a": 2, "proposer_b": 1}


def test_consensus_tie_uses_judge():
    coord = AgentCoordinator()
    coord.register_agent(Agent("a", lambda msg: "A-PROPOSAL"))
    coord.register_agent(Agent("b", lambda msg: "B-PROPOSAL"))
    coord.register_agent(Agent("judge", lambda msg: "JUDGE-SAYS: " + str(msg)))
    result = coord.run("pick best", strategy="consensus", judge="judge")
    steps = {rec["step"]: rec for rec in result["rounds"]}
    assert steps["final"]["judge"] == "judge"
    assert result["final"].startswith("JUDGE-SAYS:")


def test_consensus_needs_two_agents():
    coord = _team(["only"])
    with pytest.raises(ValueError):
        coord.run("hello", strategy="consensus")


def test_parse_vote():
    assert _parse_vote("vote: researcher", ["researcher", "critic"]) == "researcher"
    assert _parse_vote("Vote:critic", ["researcher", "critic"]) == "critic"
    assert _parse_vote("researcher", ["researcher", "critic"]) == "researcher"
    assert _parse_vote("I think vote: researcher is best", ["researcher", "critic"]) == "researcher"
    assert _parse_vote("no idea", ["researcher", "critic"]) is None


def test_run_strategy_rejects_unknown_kwargs_gracefully():
    coord = _team()
    result = coord.run("hello", strategy="broadcast", rounds=1, judge="nobody", order=["x"])
    assert result["strategy"] == "broadcast"
