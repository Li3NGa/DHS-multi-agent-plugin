"""Structured task-plan parsing and routing for the supervisor strategy."""
import json
import threading

import pytest

from deepseek_multi_agent_plugin import Agent, AgentCoordinator
from deepseek_multi_agent_plugin.agents import as_capabilities
from deepseek_multi_agent_plugin.exceptions import PlanValidationError
from deepseek_multi_agent_plugin.runtime.task import Task, TaskPlan, TaskStatus
from deepseek_multi_agent_plugin.supervisor import (
    WorkerRouter,
    _validate_and_repair,
    format_task_results,
    parse_plan,
    plan_prompt,
)


def _router(workers, caps=None):
    agents = {
        name: Agent(name, lambda msg: msg, capabilities=(caps or {}).get(name))
        for name in workers
    }
    return WorkerRouter(workers, lambda name: agents.get(name))


def test_json_plan_with_dependencies():
    text = json.dumps({"tasks": [
        {"id": "t1", "description": "research", "agent": "w1"},
        {"id": "t2", "description": "analyze", "agent": "w2", "depends_on": ["t1"]},
    ]}, ensure_ascii=False)
    plan, info = parse_plan(text, "goal", ["w1", "w2"], lambda n: None)
    assert info["format"] == "json"
    assert [t.id for t in plan.tasks] == ["t1", "t2"]
    assert plan.tasks[1].depends_on == ["t1"]
    assert plan.tasks[0].agent == "w1"


def test_fenced_json_plan_is_extracted():
    text = "计划如下：\n```json\n{\"tasks\": [{\"id\": \"a\", \"description\": \"do a\"}]}\n```"
    plan, info = parse_plan(text, "goal", ["w1"], lambda n: None)
    assert info["format"] == "json"
    assert plan.tasks[0].description == "do a"


def test_lines_fallback_assigns_round_robin():
    router = _router(["w1", "w2"])
    plan, info = parse_plan("任务A\n任务B\n任务C", "goal", ["w1", "w2"], router._agent_for)
    assert info["format"] == "lines"
    assert [t.description for t in plan.tasks] == ["任务A", "任务B", "任务C"]
    assert [t.agent for t in plan.tasks] == ["w1", "w2", "w1"]


def test_empty_plan_becomes_single_task():
    plan, info = parse_plan("", "the original goal", ["w1"], lambda n: None)
    assert info["format"] == "lines"
    assert len(plan.tasks) == 1
    assert plan.tasks[0].description == "the original goal"


def test_unknown_dependency_fallback_drops_with_note():
    # Dependency fallback is now opt-in (allow_dependency_fallback=True).
    text = json.dumps({"tasks": [
        {"id": "t1", "description": "a", "depends_on": ["ghost"]},
    ]})
    plan, info = parse_plan(text, "goal", ["w1"], lambda n: None,
                            allow_dependency_fallback=True)
    assert plan.tasks[0].depends_on == []
    assert any("ghost" in note for note in info["notes"])
    assert any("fallback" in note for note in info["notes"])


def test_cyclic_dependencies_fallback_recovers():
    # Cycle recovery is also opt-in; by default a cycle raises.
    text = json.dumps({"tasks": [
        {"id": "t1", "description": "a", "depends_on": ["t2"]},
        {"id": "t2", "description": "b", "depends_on": ["t1"]},
    ]})
    plan, info = parse_plan(text, "goal", ["w1"], lambda n: None,
                            allow_dependency_fallback=True)
    assert all(t.depends_on == [] for t in plan.tasks)
    assert any("fallback" in note for note in info["notes"])


def test_duplicate_ids_are_deduplicated():
    text = json.dumps({"tasks": [
        {"id": "t", "description": "first"},
        {"id": "t", "description": "second"},
    ]})
    plan, _ = parse_plan(text, "goal", ["w1"], lambda n: None)
    assert len(plan.tasks) == 2
    assert len({t.id for t in plan.tasks}) == 2


def test_router_prefers_explicit_worker():
    router = _router(["w1", "w2"])
    assert router.assign("w2", None) == "w2"
    assert router.assign("w1", None) == "w1"


def test_router_matches_capabilities_over_round_robin():
    router = _router(["generalist", "researcher"], caps={"researcher": "research,web"})
    assert router.assign(None, "research") == "researcher"
    assert router.assign(None, ["web"]) == "researcher"


def test_router_falls_back_when_no_capability_match():
    router = _router(["w1", "w2"], caps={"w2": "coding"})
    assert router.assign(None, "research") in {"w1", "w2"}


def test_router_ignores_unknown_preferred_worker():
    router = _router(["w1", "w2"])
    assert router.assign("ghost", None) in {"w1", "w2"}


def test_as_capabilities_normalization():
    assert as_capabilities(None) == frozenset()
    assert as_capabilities("research, web ") == frozenset({"research", "web"})
    assert as_capabilities(["a", " b ", ""]) == frozenset({"a", "b"})


def test_format_task_results_renders_status():
    text = json.dumps({"tasks": [
        {"id": "t1", "description": "ok task"},
        {"id": "t2", "description": "bad task"},
    ]})
    plan, _ = parse_plan(text, "goal", ["w1"], lambda n: None)
    results = {
        "t1": type("R", (), {"status": TaskStatus.SUCCESS, "agent": "w1",
                              "output": "done", "error": None})(),
        "t2": type("R", (), {"status": TaskStatus.FAILED, "agent": "w1",
                             "output": None, "error": "boom"})(),
    }
    rendered = format_task_results(results, plan)
    assert "[t1][w1] done" in rendered
    assert "boom" in rendered


def test_plan_prompt_contains_instructions():
    assert "JSON" in plan_prompt("goal")
    assert plan_prompt("goal").startswith("goal")


def _dag_coordinator(order):
    lock = threading.Lock()
    plan = json.dumps({"tasks": [
        {"id": "a", "description": "step a", "agent": "w1"},
        {"id": "b", "description": "step b", "agent": "w1", "depends_on": ["a"]},
        {"id": "c", "description": "step c", "agent": "w1"},
    ]}, ensure_ascii=False)

    def supervisor(msg):
        if "JSON" in str(msg):
            return plan
        return "final report"

    def worker(msg):
        with lock:
            order.append(str(msg))
        return f"done: {msg}"

    coord = AgentCoordinator()
    coord.register_agent(Agent("supervisor", supervisor))
    coord.register_agent(Agent("w1", worker))
    return coord


def test_supervisor_strategy_executes_structured_plan():
    order = []
    result = _dag_coordinator(order).run("goal", strategy="supervisor", timeout=10)
    work = {rec["step"]: rec for rec in result["rounds"]}["work"]
    assert work["plan_info"]["format"] == "json"
    assert {t["status"] for t in work["tasks"]} == {"success"}
    assert set(work["assigned"]) == {"w1"}
    assert "final report" in str(result["final"])


def test_supervisor_strategy_respects_dependencies():
    order = []
    _dag_coordinator(order).run("goal", strategy="supervisor", timeout=10)
    assert order.index("step a") < order.index("step b")


# --- Plan structural validation (TaskPlan.validate) ----------------------

def test_duplicate_task_id():
    with pytest.raises(PlanValidationError):
        TaskPlan([Task("t", "a"), Task("t", "b")])


def test_missing_dependency():
    with pytest.raises(PlanValidationError):
        TaskPlan([Task("t1", "a", depends_on=["ghost"])])


def test_self_dependency():
    with pytest.raises(PlanValidationError):
        TaskPlan([Task("t1", "a", depends_on=["t1"])])


def test_cycle_detection():
    with pytest.raises(PlanValidationError):
        TaskPlan([
            Task("t1", "a", depends_on=["t2"]),
            Task("t2", "b", depends_on=["t1"]),
        ])


def test_invalid_agent():
    plan = TaskPlan([Task("t1", "a", agent="ghost")])
    with pytest.raises(PlanValidationError):
        plan.validate(known_agents={"w1", "w2"})


def test_invalid_capability():
    plan = TaskPlan([Task("t1", "a", required_capabilities=["research"])])
    with pytest.raises(PlanValidationError):
        plan.validate(known_agents={"w1"}, known_capabilities=set())


def test_malformed_task_rejected():
    with pytest.raises(PlanValidationError):
        TaskPlan([Task("t1", "")])


# --- Repair pipeline ------------------------------------------------------

def test_repair_success():
    # An unknown agent is re-routed to a real worker (semantically safe),
    # so the plan validates after a single repair pass.
    text = json.dumps({"tasks": [
        {"id": "t1", "description": "a", "agent": "ghost"},
        {"id": "t2", "description": "b", "agent": "w2"},
    ]})
    plan, info = parse_plan(text, "goal", ["w1", "w2"], lambda n: None)
    assert plan.tasks[0].agent in {"w1", "w2"}   # reassigned, not "ghost"
    assert plan.tasks[1].agent == "w2"           # valid agent untouched
    assert any("ghost" in note for note in info["notes"])


def test_repair_failure():
    # A dependency cycle cannot be repaired without deleting edges, so the
    # default strict mode raises PlanValidationError (the Run will FAIL).
    text = json.dumps({"tasks": [
        {"id": "t1", "description": "a", "depends_on": ["t2"]},
        {"id": "t2", "description": "b", "depends_on": ["t1"]},
    ]})
    with pytest.raises(PlanValidationError):
        parse_plan(text, "goal", ["w1"], lambda n: None)


def test_no_silent_dependency_removal():
    # Even after the repair attempts, a structurally-broken plan keeps its
    # dependencies intact: the pipeline raises instead of clearing them.
    tasks = [
        Task("t1", "a", depends_on=["t2"]),
        Task("t2", "b", depends_on=["t1"]),
    ]
    router = WorkerRouter(["w1"], lambda n: None)
    with pytest.raises(PlanValidationError):
        _validate_and_repair(
            tasks, router, {"w1"}, set(), {"notes": []},
            allow_dependency_fallback=False, max_repair_attempts=2,
        )
    # dependencies were never silently emptied to force validation through
    assert tasks[0].depends_on == ["t2"]
    assert tasks[1].depends_on == ["t1"]


def test_repair_is_limited_in_attempts():
    # Two workers so the unknown-agent repair succeeds; verify the repair
    # note is recorded exactly as many times as attempts were needed (here
    # it converges after the first repair pass, not an unbounded loop).
    text = json.dumps({"tasks": [
        {"id": "t", "description": "a", "agent": "ghost"},
    ]})
    plan, info = parse_plan(text, "goal", ["w1", "w2"], lambda n: None,
                            max_repair_attempts=2)
    assert plan.tasks[0].agent in {"w1", "w2"}
    assert sum("ghost" in note for note in info["notes"]) == 1
