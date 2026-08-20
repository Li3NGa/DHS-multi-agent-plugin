"""Task orchestration runtime.

Structured task model plus a dependency-aware scheduler that executes
task plans as a DAG: independent tasks run in parallel, dependent tasks
wait for their dependencies, and failures cascade as SKIPPED.
"""
from .dependency import topological_order
from .executor import shared_executor, shutdown_executor
from .scheduler import TaskScheduler
from .task import Task, TaskPlan, TaskResult, TaskStatus

__all__ = [
    "Task",
    "TaskPlan",
    "TaskResult",
    "TaskStatus",
    "TaskScheduler",
    "shared_executor",
    "shutdown_executor",
    "topological_order",
]
