"""Dependency graph helpers for task plans."""
from typing import Dict, Iterable, List

from ..exceptions import PlanError


def topological_order(ids: Iterable[str], depends_on: Dict[str, Iterable[str]]) -> List[str]:
    """Kahn's algorithm over ``{id: [deps]}``.

    Raises PlanError when a dependency is unknown or the graph has a
    cycle; the error names the offending edge/nodes so callers can point
    the LLM planner at the exact problem.
    """
    known = set(ids)
    pending_deps = {i: set(depends_on.get(i, ())) for i in known}
    for task_id, deps in pending_deps.items():
        unknown = deps - known
        if unknown:
            raise PlanError(f"task '{task_id}' depends on unknown tasks: {sorted(unknown)}")

    dependents: Dict[str, List[str]] = {i: [] for i in known}
    for task_id, deps in pending_deps.items():
        for dep in deps:
            dependents[dep].append(task_id)

    ready = sorted(i for i, deps in pending_deps.items() if not deps)
    order: List[str] = []
    while ready:
        task_id = ready.pop(0)
        order.append(task_id)
        for follower in dependents[task_id]:
            pending_deps[follower].discard(task_id)
            if not pending_deps[follower]:
                ready.append(follower)

    if len(order) != len(known):
        stuck = sorted(i for i, deps in pending_deps.items() if deps)
        raise PlanError(f"dependency cycle detected involving tasks: {stuck}")
    return order
