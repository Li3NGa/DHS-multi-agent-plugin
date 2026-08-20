"""Structured task planning for the supervisor strategy.

The supervisor agent is asked for a JSON task plan; the plan is parsed
into a runtime TaskPlan, routed to workers (explicit agent name >
capability match > round-robin) and executed on the DAG scheduler.

Free-form (non-JSON) supervisor output falls back to the legacy
one-task-per-line format, so mock/script supervisors keep working.
Plans whose dependencies form a cycle are recovered by dropping the
edges rather than failing the whole run.
"""
import json
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .agents import Agent, as_capabilities
from .exceptions import PlanError
from .runtime import Task, TaskPlan

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


def _tasks_from_json(raw: List[Dict[str, Any]], router: WorkerRouter) -> List[Task]:
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
        tasks.append(Task(
            id=task_id,
            description=description,
            agent=router.assign(entry.get("agent"), entry.get("required_capabilities")),
            depends_on=depends_on,
            required_capabilities=sorted(as_capabilities(entry.get("required_capabilities"))),
        ))
    return tasks


def _tasks_from_lines(text: str, router: WorkerRouter, prompt: str) -> List[Task]:
    lines = [ln.strip().lstrip("-*0123456789. ") for ln in str(text).splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return [Task(id="task_1", description=str(prompt), agent=router.assign(None, None))]
    return [
        Task(id=f"task_{i}", description=ln, agent=router.assign(None, None))
        for i, ln in enumerate(lines, 1)
    ]


def _resolve_dependencies(tasks: List[Task], notes: List[str]) -> None:
    known = {t.id for t in tasks}
    for task in tasks:
        unknown = [d for d in task.depends_on if d not in known]
        if unknown:
            notes.append(f"task '{task.id}': dropped unknown dependencies {unknown}")
            task.depends_on = [d for d in task.depends_on if d in known]
        if task.id in task.depends_on:
            task.depends_on.remove(task.id)


def parse_plan(
    text: str,
    prompt: str,
    workers: Sequence[str],
    agent_for: Callable[[str], Optional[Agent]],
) -> Tuple[TaskPlan, Dict[str, Any]]:
    """Parse supervisor output into a validated TaskPlan.

    Returns (plan, info); info records the source format ("json" or
    "lines") and any recovery notes (dropped edges, rejected ids).
    """
    router = WorkerRouter(workers, agent_for)
    info: Dict[str, Any] = {"format": "lines", "notes": []}
    raw = _parse_json_tasks(text)
    if raw:
        tasks = _tasks_from_json(raw, router)
        if tasks:
            info["format"] = "json"
        else:
            tasks = _tasks_from_lines(text, router, prompt)
    else:
        tasks = _tasks_from_lines(text, router, prompt)

    _resolve_dependencies(tasks, info["notes"])
    try:
        plan = TaskPlan(tasks)
    except PlanError as exc:
        # Cycles and other structural leftovers: keep the decomposition,
        # drop the dependency edges.
        info["notes"].append(f"dependencies dropped: {exc}")
        for task in tasks:
            task.depends_on = []
        plan = TaskPlan(tasks)
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
