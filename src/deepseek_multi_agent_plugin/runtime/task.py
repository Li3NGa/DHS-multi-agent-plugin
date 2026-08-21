"""Structured task model for orchestrated runs.

A TaskPlan is a flat set of named tasks with ``depends_on`` edges; the
scheduler (see .scheduler) executes it as a DAG. Statuses mirror the
task lifecycle: pending -> running -> success | failed | timeout, plus
cancelled (run aborted) and skipped (a dependency did not succeed).
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from ..exceptions import PlanError, PlanValidationError


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL


_TERMINAL = frozenset({
    TaskStatus.SUCCESS,
    TaskStatus.FAILED,
    TaskStatus.TIMEOUT,
    TaskStatus.CANCELLED,
    TaskStatus.SKIPPED,
})


@dataclass
class Task:
    """One unit of work, typically produced by a supervisor's plan."""

    id: str
    description: str
    agent: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)
    required_capabilities: List[str] = field(default_factory=list)
    timeout: Optional[float] = None
    status: TaskStatus = TaskStatus.PENDING

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "id": self.id,
            "description": self.description,
            "status": self.status.value,
        }
        if self.agent is not None:
            out["agent"] = self.agent
        if self.depends_on:
            out["depends_on"] = list(self.depends_on)
        if self.required_capabilities:
            out["required_capabilities"] = list(self.required_capabilities)
        if self.timeout is not None:
            out["timeout"] = self.timeout
        return out


@dataclass
class TaskResult:
    """Terminal outcome of one task."""

    task_id: str
    status: TaskStatus
    output: Any = None
    error: Optional[str] = None
    agent: Optional[str] = None
    duration_ms: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "task_id": self.task_id,
            "status": self.status.value,
        }
        if self.agent is not None:
            out["agent"] = self.agent
        if self.error is not None:
            out["error"] = self.error
        if self.output is not None:
            out["output"] = self.output
        out["duration_ms"] = round(self.duration_ms, 1)
        return out


class TaskPlan:
    """Validated collection of tasks with dependency edges.

    Construction rejects duplicate ids, unknown dependencies, self
    dependencies and dependency cycles. Validation is *strict* and never
    mutates the plan to "repair" it: callers are expected to run a separate
    Validate -> Repair -> Validate loop (see the supervisor) and only then
    execute. When repair cannot fix a problem, :class:`PlanValidationError`
    is raised so the owning Run can be marked FAILED instead of silently
    executing a degraded plan with its semantics changed.
    """

    def __init__(self, tasks: List[Task]):
        self.tasks: List[Task] = list(tasks)
        self._by_id: Dict[str, Task] = {}
        for task in self.tasks:
            if not task.id:
                raise PlanValidationError("task id must be non-empty")
            if task.id in self._by_id:
                raise PlanValidationError(f"duplicate task id: {task.id}")
            self._by_id[task.id] = task
        self.validate()

    def validate(
        self,
        known_agents: Optional[set] = None,
        known_capabilities: Optional[set] = None,
    ) -> None:
        """Reject structurally or semantically invalid plans.

        ``known_agents`` / ``known_capabilities`` are optional so the graph
        shape can be validated before the worker pool is known. When supplied
        they also gate agent / capability references.

        Raises :class:`PlanValidationError` (a subclass of ``PlanError``) on
        the first problem found. Check order: malformed task, missing
        dependency, self dependency, cycle, unknown agent, unsupported
        capability.
        """
        for task in self.tasks:
            if not task.description or not str(task.description).strip():
                raise PlanValidationError(
                    f"task '{task.id}' is malformed: missing description"
                )

        for task in self.tasks:
            for dep in task.depends_on:
                if dep not in self._by_id:
                    raise PlanValidationError(
                        f"task '{task.id}' depends on unknown task '{dep}'"
                    )
                if dep == task.id:
                    raise PlanValidationError(
                        f"task '{task.id}' depends on itself (self-cycle)"
                    )

        # topological sort doubles as a cycle check
        try:
            self.topological_order()
        except PlanError as exc:
            raise PlanValidationError(str(exc)) from exc

        if known_agents is not None:
            known = set(known_agents)
            for task in self.tasks:
                if task.agent is not None and task.agent not in known:
                    raise PlanValidationError(
                        f"task '{task.id}' references unknown agent "
                        f"'{task.agent}'"
                    )
        if known_capabilities is not None:
            known_caps = set(known_capabilities)
            for task in self.tasks:
                for cap in task.required_capabilities:
                    if cap not in known_caps:
                        raise PlanValidationError(
                            f"task '{task.id}' requires unsupported capability "
                            f"'{cap}'"
                        )

    def topological_order(self) -> List[str]:
        from .dependency import topological_order

        return topological_order(
            [t.id for t in self.tasks],
            {t.id: t.depends_on for t in self.tasks},
        )

    def get(self, task_id: str) -> Optional[Task]:
        return self._by_id.get(task_id)

    def __len__(self) -> int:
        return len(self.tasks)

    def __iter__(self):
        return iter(self.tasks)

    def as_dict(self) -> List[Dict[str, Any]]:
        return [t.as_dict() for t in self.tasks]
