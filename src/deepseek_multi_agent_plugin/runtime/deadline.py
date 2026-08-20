"""Run-level deadline propagation.

A run started with ``run_timeout`` installs an absolute deadline in a
contextvar. Every agent dispatch point clamps its per-call timeout to the
remaining budget and refuses to start new work once the budget is spent
(``RunTimeout``). The deadline is cooperative: calls already in flight
finish on their own timeout and their spans are still recorded.

Workers on the shared executor cannot see the caller's contextvar, so the
clamp happens on the dispatching thread (in ``_call_agent`` / ``_parallel``
/ the scheduler) before the work is submitted.
"""
import time
from contextvars import ContextVar
from typing import Optional

from ..exceptions import RunTimeout

_deadline: ContextVar[Optional[float]] = ContextVar("dsma_run_deadline", default=None)


def start_run_deadline(seconds: Optional[float]):
    """Install a run deadline; returns a token for :func:`end_run_deadline`."""
    if seconds is None:
        return None
    return _deadline.set(time.monotonic() + float(seconds))


def end_run_deadline(token) -> None:
    if token is not None:
        _deadline.reset(token)


def run_deadline() -> Optional[float]:
    """Absolute monotonic deadline of the current run, if any."""
    return _deadline.get()


def clamp_timeout(timeout: Optional[float]) -> Optional[float]:
    """Bound a per-call timeout by the remaining run budget.

    Raises RunTimeout when the budget is already spent, so callers never
    dispatch new work past the deadline.
    """
    deadline = _deadline.get()
    if deadline is None:
        return timeout
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RunTimeout("run deadline exceeded")
    return remaining if timeout is None else min(timeout, remaining)
