"""Structured task model for orchestrated runs.

A TaskPlan is a flat set of named tasks with ``depends_on`` edges; the
scheduler (see .scheduler) executes it as a DAG. Statuses mirror the
task lifecycle: pending -> running -> success | failed | timeout, plus
cancelled (run aborted) and skipped (a dependency did not succeed).
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from ..exceptions import PlanError


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

    Construction rejects duplicate ids, unknown dependencies and
    dependency cycles (PlanError).
    """

    def __init__(self, tasks: List[Task]):
        self.tasks: List[Task] = list(tasks)
        self._by_id: Dict[str, Task] = {}
        for task in self.tasks:
            if not task.id:
                raise PlanError("task id must be non-empty")
            if task.id in self._by_id:
                raise PlanError(f"duplicate task id: {task.id}")
            self._by_id[task.id] = task
        self.validate()

    def validate(self) -> None:
        for task in self.tasks:
            for dep in task.depends_on:
                if dep not in self._by_id:
                    raise PlanError(f"task '{task.id}' depends on unknown task '{dep}'")
        self.topological_order()

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
