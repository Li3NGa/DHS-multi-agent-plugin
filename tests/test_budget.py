"""Run-level execution budgets: reservation semantics, limits, wiring."""
import json
import time

import pytest

from deepseek_multi_agent_plugin import Agent, AgentCoordinator, BudgetManager
from deepseek_multi_agent_plugin.exceptions import BudgetExceeded, RunTimeout


def _usage_agent(name, tokens):
    """Agent that bills ``tokens`` per call by bumping its usage counters."""
    agent = Agent(name)

    def handler(msg):
        agent._add_usage({
            "prompt_tokens": tokens // 2,
            "completion_tokens": tokens - tokens // 2,
            "total_tokens": tokens,
        })
        return f"{name}: {msg}"

    agent._handler = handler
    return agent


# ---------------------------------------------------------------- BudgetManager
def test_reserve_enforces_max_calls_atomically():
    budget = BudgetManager(max_calls=2)
    budget.reserve()
    budget.reserve()
    with pytest.raises(BudgetExceeded):
        budget.reserve()


def test_settle_accounts_tokens_and_consumes_reservation():
    budget = BudgetManager(max_calls=1, max_tokens=100)
    budget.reserve()
    budget.settle({"total_tokens": 40})
    snap = budget.snapshot()
    assert snap["calls"] == 1
    assert snap["in_flight"] == 0
    assert snap["tokens"] == 40
    with pytest.raises(BudgetExceeded):  # call budget spent, not token budget
        budget.reserve()


def test_token_limit_blocks_next_call():
    budget = BudgetManager(max_tokens=100)
    budget.reserve()
    budget.settle({"total_tokens": 100})
    with pytest.raises(BudgetExceeded):
        budget.reserve()


def test_cost_limit_uses_pricer():
    def pricer(usage):
        return usage.get("total_tokens", 0) / 1000.0

    budget = BudgetManager(max_cost=0.5, pricer=pricer)
    for _ in range(4):  # 4 * 0.125 = 0.5 -> at the limit
        budget.reserve()
        budget.settle({"total_tokens": 125})
    with pytest.raises(BudgetExceeded):
        budget.reserve()


def test_failed_calls_still_consume_the_call_budget():
    budget = BudgetManager(max_calls=1)
    budget.reserve()
    budget.settle()  # no usage dict: the call still happened
    with pytest.raises(BudgetExceeded):
        budget.reserve()


# ---------------------------------------------------------------- coercion
def test_as_budget_accepts_manager_dict_and_none():
    from deepseek_multi_agent_plugin.runtime import as_budget

    assert as_budget(None) is None
    shared = BudgetManager(max_calls=3)
    assert as_budget(shared) is shared
    coerced = as_budget({"max_calls": 5, "max_tokens": 1000})
    assert coerced.max_calls == 5
    assert coerced.max_tokens == 1000


def test_as_budget_rejects_unknown_keys():
    from deepseek_multi_agent_plugin.runtime import as_budget

    with pytest.raises(ValueError):
        as_budget({"max_call": 5})


def test_as_budget_rejects_negative_limits():
    from deepseek_multi_agent_plugin.runtime import as_budget

    for bad in ({"max_calls": -1}, {"max_tokens": -10},
                {"max_cost": -0.5}, {"max_seconds": -1}):
        with pytest.raises(ValueError, match="must be >= 0"):
            as_budget(bad)


# ---------------------------------------------------------------- run wiring
def test_run_budget_dict_stops_parallel_broadcast():
    coord = AgentCoordinator()
    coord.register_agent(Agent("a", lambda msg: "a"))
    coord.register_agent(Agent("b", lambda msg: "b"))
    coord.register_agent(Agent("c", lambda msg: "c"))
    with pytest.raises(BudgetExceeded):
        coord.run("hello", strategy="broadcast", budget={"max_calls": 2})


def test_run_budget_reports_snapshot_in_meta():
    coord = AgentCoordinator()
    coord.register_agent(Agent("a", lambda msg: "a"))
    coord.register_agent(Agent("b", lambda msg: "b"))
    result = coord.run("hello", strategy="broadcast", budget={"max_calls": 10})
    assert result["meta"]["budget"]["calls"] == 2
    assert result["meta"]["budget"]["limits"]["max_calls"] == 10
    assert result["meta"]["budget"]["in_flight"] == 0


def test_run_budget_counts_llm_tokens_via_usage_counters():
    coord = AgentCoordinator()
    coord.register_agent(_usage_agent("llm", 30))
    coord.register_agent(_usage_agent("llm2", 30))
    result = coord.run("hello", strategy="broadcast", budget={"max_tokens": 100})
    assert result["meta"]["budget"]["tokens"] == 60


def test_run_budget_token_limit_blocks_later_calls():
    coord = AgentCoordinator()
    coord.register_agent(_usage_agent("a", 40))
    coord.register_agent(_usage_agent("b", 40))
    coord.register_agent(_usage_agent("c", 40))
    with pytest.raises(BudgetExceeded):
        coord.run("hello", strategy="sequential", budget={"max_tokens": 80})


def test_parallel_batch_may_overshoot_token_budget():
    # token counts are only known after a reply, so one in-flight batch can
    # overshoot; the budget then blocks all further calls (here: round 2)
    coord = AgentCoordinator()
    coord.register_agent(_usage_agent("big", 80))
    coord.register_agent(_usage_agent("big2", 80))
    with pytest.raises(BudgetExceeded):
        coord.run("hello", strategy="broadcast", rounds=2, budget={"max_tokens": 100})


def test_run_budget_max_seconds_flows_into_deadline():
    coord = AgentCoordinator(timeout=30.0)
    coord.register_agent(Agent("slow", lambda msg: (time.sleep(5.0), "late")[1]))
    with pytest.raises(RunTimeout):
        coord.run("hello", strategy="broadcast", budget={"max_seconds": 0.2})


def test_budget_max_seconds_tightens_existing_run_timeout():
    coord = AgentCoordinator()
    coord.register_agent(Agent("slow", lambda msg: (time.sleep(5.0), "late")[1]))
    with pytest.raises(RunTimeout):
        coord.run("hello", strategy="broadcast", run_timeout=10.0, budget={"max_seconds": 0.2})


# ---------------------------------------------------------------- supervisor/DAG
def _supervisor_coord():
    plan = json.dumps({"tasks": [
        {"id": "t1", "description": "one", "agent": "w"},
        {"id": "t2", "description": "two", "agent": "w"},
        {"id": "t3", "description": "three", "agent": "w", "depends_on": ["t2"]},
    ]})

    def supervisor(msg):
        return plan if "JSON" in str(msg) else "report"

    coord = AgentCoordinator()
    coord.register_agent(Agent("supervisor", supervisor))
    coord.register_agent(Agent("w", lambda msg: f"done: {msg}"))
    return coord


def test_supervisor_budget_counts_plan_tasks_and_report():
    coord = _supervisor_coord()
    result = coord.run("goal", strategy="supervisor", budget={"max_calls": 10})
    # plan + 3 tasks + report
    assert result["meta"]["budget"]["calls"] == 5


def test_supervisor_budget_exhaustion_aborts_plan():
    coord = _supervisor_coord()
    with pytest.raises(BudgetExceeded):
        coord.run("goal", strategy="supervisor", budget={"max_calls": 2})


def test_shared_budget_manager_spans_runs():
    budget = BudgetManager(max_calls=1)
    coord = AgentCoordinator()
    coord.register_agent(Agent("a", lambda msg: "a"))
    coord.run("one", strategy="broadcast", budget=budget)
    with pytest.raises(BudgetExceeded):
        coord.run("two", strategy="broadcast", budget=budget)


# ---------------------------------------------------------------- coordinator defaults
def test_default_budget_applies_fresh_per_run():
    coord = AgentCoordinator(budget={"max_calls": 1})
    coord.register_agent(Agent("a", lambda msg: "a"))
    first = coord.run("one", strategy="broadcast")
    assert first["meta"]["budget"]["calls"] == 1
    second = coord.run("two", strategy="broadcast")  # fresh budget again
    assert second["meta"]["budget"]["calls"] == 1


def test_run_level_budget_overrides_default():
    coord = AgentCoordinator(budget={"max_calls": 10})
    coord.register_agent(Agent("a", lambda msg: "a"))
    coord.register_agent(Agent("b", lambda msg: "b"))
    with pytest.raises(BudgetExceeded):
        coord.run("hello", strategy="broadcast", budget={"max_calls": 1})


def test_config_build_coordinator_applies_budget_defaults():
    from deepseek_multi_agent_plugin.config import build_coordinator

    coord = build_coordinator(config={
        "coordinator": {"budget": {"max_calls": 1}},
        "agents": [{"name": "a", "kind": "mock"}],
    })
    assert coord.default_budget == {"max_calls": 1}
    result = coord.run("hello", strategy="broadcast")
    assert result["meta"]["budget"]["calls"] == 1


def test_adapter_event_forwards_budget():
    from deepseek_multi_agent_plugin.coordinator import DeepseekAdapter

    coord = AgentCoordinator()
    coord.register_agent(Agent("a", lambda msg: "a"))
    coord.register_agent(Agent("b", lambda msg: "b"))
    adapter = DeepseekAdapter(coord)
    result = adapter.handle_harness_event({
        "type": "run",
        "prompt": "hello",
        "strategy": "broadcast",
        "budget": {"max_calls": 10},
    })
    assert result["meta"]["budget"]["calls"] == 2
