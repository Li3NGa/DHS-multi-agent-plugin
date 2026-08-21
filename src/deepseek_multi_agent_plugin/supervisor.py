"""Structured task planning for the supervisor strategy.

The supervisor agent is asked for a JSON task plan; the plan is parsed
into a runtime TaskPlan, routed to workers (explicit agent name >
capability match > round-robin) and executed on the DAG scheduler.

Free-form (non-JSON) supervisor output falls back to the legacy
one-task-per-line format, so mock/script supervisors keep working.

Pipeline:  parse -> TaskPlan -> Validate -> Repair -> Validate -> Execute.

Structural correctness is strict. When a plan fails validation we run a
*limited* repair pass (default ``max_repair_attempts=2``) that only makes
semantically-safe changes (re-route an unknown agent to a real worker,
drop unsatisfiable capability requirements). It never clears
``depends_on`` to paper over a real dependency problem, because that would
silently change the task graph. If the plan is still invalid after repair
the owning Run is marked FAILED (``PlanValidationError`` raised) — unless
the caller opts into ``allow_dependency_fallback``, which re-enables the
legacy "drop the offending edges and keep going" behaviour.
"""
import json
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .agents import Agent, as_capabilities
from .exceptions import PlanValidationError
from .runtime import Task, TaskPlan
from .runtime.dependency import topological_order

PLAN_INSTRUCTIONS = """请把上面的任务分解为一个 JSON 任务计划，格式如下（只输出 JSON，不要其他文字）：
{
  "tasks": [
    {
      "id": "task_1",
      "description": "子任务描述",
      "agent": "worker 名称（可留空，由系统自动分配）",
      "depends_on": ["前置任务的 id，没有依赖则为空数组"],
      "required_capabilities": ["该子任务需要的能力，如 research/coding/analysis"]
    }
  ]
}
子任务应当数量适中（通常 2-6 个）；可以并行的工作不要人为制造依赖。"""

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def plan_prompt(prompt: str) -> str:
    return f"{prompt}\n\n{PLAN_INSTRUCTIONS}"


class WorkerRouter:
    """Assign tasks to workers: explicit name > capability match > round-robin."""

    def __init__(self, workers: Sequence[str], agent_for: Callable[[str], Optional[Agent]]):
        self._workers = list(workers)
        self._agent_for = agent_for
        self._cursor = 0

    def _capabilities(self, name: str) -> frozenset:
        agent = self._agent_for(name)
        return agent.capabilities if agent is not None else frozenset()

    def assign(self, preferred: Optional[str], required: Any) -> str:
        if preferred and preferred in self._workers:
            return preferred
        required_caps = as_capabilities(required)
        if required_caps:
            candidates = [
                w for w in self._workers
                if required_caps <= self._capabilities(w)
            ]
            if candidates:
                return self._round_robin(candidates)
        return self._round_robin(self._workers)

    def _round_robin(self, pool: List[str]) -> str:
        name = pool[self._cursor % len(pool)]
        self._cursor += 1
        return name


def _parse_json_tasks(text: str) -> Optional[List[Dict[str, Any]]]:
    for candidate in _json_candidates(text):
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            tasks = data.get("tasks")
        elif isinstance(data, list):
            tasks = data
        else:
            continue
        if isinstance(tasks, list):
            return [t for t in tasks if isinstance(t, dict)]
        return None
    return None


def _json_candidates(text: str) -> List[str]:
    candidates = [m.group(1).strip() for m in _FENCE_RE.finditer(text)]
    first, last = text.find("{"), text.rfind("}")
    if first != -1 and last > first:
        candidates.append(text[first:last + 1])
    candidates.append(text.strip())
    return candidates


def _tasks_from_json(raw: List[Dict[str, Any]]) -> List[Task]:
    tasks: List[Task] = []
    used_ids: set[str] = set()
    for i, entry in enumerate(raw, 1):
        description = str(entry.get("description") or entry.get("task") or "").strip()
        if not description:
            continue
        task_id = str(entry.get("id") or f"task_{i}").strip() or f"task_{i}"
        while task_id in used_ids:  # LLM plans sometimes reuse ids
            task_id = f"{task_id}_r{len(used_ids)}"
        used_ids.add(task_id)
        depends_on = [
            str(dep).strip() for dep in (entry.get("depends_on") or [])
            if str(dep).strip()
        ]
        # NOTE: the requested agent is kept verbatim so validation can detect
        # an *unknown* agent. Concrete routing happens later (see
        # _route_agents) once the plan has been validated / repaired.
        tasks.append(Task(
            id=task_id,
            description=description,
            agent=str(entry["agent"]).strip() if entry.get("agent") else None,
            depends_on=depends_on,
            required_capabilities=sorted(as_capabilities(entry.get("required_capabilities"))),
        ))
    return tasks


def _tasks_from_lines(text: str, prompt: str) -> List[Task]:
    lines = [ln.strip().lstrip("-*0123456789. ") for ln in str(text).splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return [Task(id="task_1", description=str(prompt))]
    return [
        Task(id=f"task_{i}", description=ln)
        for i, ln in enumerate(lines, 1)
    ]


def _route_agents(tasks: List[Task], router: WorkerRouter) -> None:
    """Assign every task a concrete worker.

    Idempotent for tasks whose agent is already a valid worker; assigns
    round-robin for tasks left with no agent; re-routes an agent that was
    repaired from an unknown name.
    """
    for task in tasks:
        task.agent = router.assign(task.agent, task.required_capabilities)


def _repair_tasks(
    tasks: List[Task],
    router: WorkerRouter,
    known_agents: set,
    known_caps: set,
    info: Dict[str, Any],
) -> None:
    """Attempt to fix a plan WITHOUT changing task semantics.

    Safe repairs:
      * an unknown / missing agent is re-routed to a concrete worker;
      * capability requirements no worker satisfies are dropped (they are
        unsatisfiable and only constrain routing, not a task's meaning).

    NOT done here (they would alter dependencies / semantics): missing
    dependencies, self-dependencies, cycles. Those need either another
    repair pass (e.g. re-planning) or an explicit ``allow_dependency_fallback``.
    """
    for task in tasks:
        before = task.agent
        task.agent = router.assign(task.agent, task.required_capabilities)
        if before is not None and before not in known_agents and task.agent != before:
            info["notes"].append(
                f"task '{task.id}': reassigned unknown agent '{before}' -> "
                f"'{task.agent}'"
            )
        bad_caps = [c for c in task.required_capabilities if c not in known_caps]
        if bad_caps:
            task.required_capabilities = [
                c for c in task.required_capabilities if c in known_caps
            ]
            info["notes"].append(
                f"task '{task.id}': dropped unsupported capabilities {bad_caps}"
            )


def _apply_dependency_fallback(tasks: List[Task], info: Dict[str, Any]) -> None:
    """Opt-in recovery: drop offending dependency edges (legacy behaviour).

    Only reached when ``allow_dependency_fallback`` is True. This is the one
    place allowed to mutate ``depends_on`` to resolve a structural problem,
    and only because the caller explicitly opted in.
    """
    known_ids = {t.id for t in tasks}
    for task in tasks:
        kept = [d for d in task.depends_on if d in known_ids and d != task.id]
        dropped = [d for d in task.depends_on if d not in kept]
        if dropped:
            info["notes"].append(
                f"task '{task.id}': dropped dependencies {dropped} (fallback)"
            )
            task.depends_on = kept
    # break remaining cycles by clearing all edges
    ids = [t.id for t in tasks]
    edges = {t.id: t.depends_on for t in tasks}
    try:
        topological_order(ids, edges)
    except PlanValidationError:
        for task in tasks:
            if task.depends_on:
                info["notes"].append(
                    f"task '{task.id}': cleared dependency cycle (fallback)"
                )
                task.depends_on = []


def _validate_and_repair(
    tasks: List[Task],
    router: WorkerRouter,
    known_agents: set,
    known_caps: set,
    info: Dict[str, Any],
    *,
    allow_dependency_fallback: bool,
    max_repair_attempts: int,
) -> TaskPlan:
    attempts = max(0, int(max_repair_attempts))
    last_error: Optional[PlanValidationError] = None
    for attempt in range(attempts + 1):
        try:
            plan = TaskPlan(tasks)
            plan.validate(known_agents, known_caps)
            _route_agents(tasks, router)
            return plan
        except PlanValidationError as exc:
            last_error = exc
            if attempt < attempts:  # limited repair, never on the final pass
                _repair_tasks(tasks, router, known_agents, known_caps, info)
    # Repair exhausted: fail the run (strict, default) or apply the opt-in
    # dependency fallback.
    if allow_dependency_fallback:
        _apply_dependency_fallback(tasks, info)
        plan = TaskPlan(tasks)
        plan.validate(known_agents, known_caps)
        _route_agents(tasks, router)
        return plan
    assert last_error is not None
    raise last_error


def parse_plan(
    text: str,
    prompt: str,
    workers: Sequence[str],
    agent_for: Callable[[str], Optional[Agent]],
    *,
    allow_dependency_fallback: bool = False,
    max_repair_attempts: int = 2,
) -> Tuple[TaskPlan, Dict[str, Any]]:
    """Parse supervisor output into a validated, strictly-correct TaskPlan.

    Pipeline: parse -> TaskPlan -> Validate -> Repair -> Validate -> Execute.

    The plan is checked for duplicate / empty id, missing or self
    dependency, cycles, unknown agents, unsupported capabilities and missing
    descriptions. If validation fails, a *limited* repair pass is attempted
    (default ``max_repair_attempts=2``). Repair only performs changes that do
    NOT alter task semantics (re-route an unknown agent to a real worker;
    drop capability requirements no worker can satisfy). It never clears
    ``depends_on`` to paper over a structural problem.

    If the plan is still invalid after repair:
      * when ``allow_dependency_fallback`` is True, the offending dependency
        edges are dropped (the historical recovery behaviour) and the run
        continues with a degraded plan;
      * otherwise ``PlanValidationError`` is raised so the owning Run is
        marked FAILED instead of executing a silently-degraded plan.

    Returns (plan, info). ``info`` records the source format ("json"/"lines")
    and any repair / fallback notes.
    """
    router = WorkerRouter(workers, agent_for)
    known_agents = set(workers)
    known_caps: set[str] = set()
    for w in workers:
        agent = agent_for(w)
        if agent is not None:
            known_caps |= agent.capabilities

    info: Dict[str, Any] = {"format": "lines", "notes": []}
    raw = _parse_json_tasks(text)
    if raw:
        tasks = _tasks_from_json(raw)
        if tasks:
            info["format"] = "json"
        else:
            tasks = _tasks_from_lines(text, prompt)
    else:
        tasks = _tasks_from_lines(text, prompt)

    plan = _validate_and_repair(
        tasks,
        router,
        known_agents,
        known_caps,
        info,
        allow_dependency_fallback=allow_dependency_fallback,
        max_repair_attempts=max_repair_attempts,
    )
    return plan, info


def format_task_results(results: Dict[str, Any], plan: TaskPlan) -> str:
    """Render scheduler results as the supervisor's report input."""
    parts = []
    for task in plan.tasks:
        result = results.get(task.id)
        if result is None:
            continue
        if result.status.value == "success":
            parts.append(f"[{task.id}][{result.agent}] {result.output}")
        else:
            parts.append(f"[{task.id}][{result.agent}] 未完成（{result.status.value}: {result.error}）")
    return "\n\n".join(parts)
