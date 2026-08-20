"""Task orchestration runtime.

Structured task model plus a dependency-aware scheduler that executes
task plans as a DAG: independent tasks run in parallel, dependent tasks
wait for their dependencies, and failures cascade as SKIPPED.
"""
from .deadline import clamp_timeout, end_run_deadline, run_deadline, start_run_deadline
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
    "clamp_timeout",
    "end_run_deadline",
    "run_deadline",
    "shared_executor",
    "shutdown_executor",
    "start_run_deadline",
    "topological_order",
]
