"""Task orchestration runtime.

Structured task model plus a dependency-aware scheduler that executes
task plans as a DAG: independent tasks run in parallel, dependent tasks
wait for their dependencies, and failures cascade as SKIPPED. Run-level
concerns (deadline, execution budget) propagate through contextvars.
"""
from .budget import BudgetManager, as_budget, current_budget, end_run_budget, start_run_budget
from .deadline import clamp_timeout, end_run_deadline, run_deadline, start_run_deadline
from .dependency import topological_order
from .executor import shared_executor, shutdown_executor
from .scheduler import TaskScheduler
from .task import Task, TaskPlan, TaskResult, TaskStatus

__all__ = [
    "BudgetManager",
    "Task",
    "TaskPlan",
    "TaskResult",
    "TaskStatus",
    "TaskScheduler",
    "as_budget",
    "clamp_timeout",
    "current_budget",
    "end_run_budget",
    "end_run_deadline",
    "run_deadline",
    "shared_executor",
    "shutdown_executor",
    "start_run_budget",
    "start_run_deadline",
    "topological_order",
]
