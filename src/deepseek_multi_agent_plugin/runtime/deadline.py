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
    """Install a run deadline; returns a token for :func:`end_run_deadline`.

    Negative values are clamped to 0 (deadline already spent), keeping the
    cooperative deadline semantics well-defined: ``Future.result(timeout<0)``
    would otherwise wait forever instead of timing out.
    """
    if seconds is None:
        return None
    return _deadline.set(time.monotonic() + max(0.0, float(seconds)))


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
    # 对齐到微秒精度，消除浮点尾差（如 0.3000000000001819）导致的
    # 外部断言不一致；取整误差 <=0.5us，远小于 strategies 中
    # `run_dl - now <= timeout` 的判定余量，不会翻转 RunTimeout 语义。
    remaining = round(remaining, 6)
    if remaining <= 0:
        raise RunTimeout("run deadline exceeded")
    return remaining if timeout is None else min(timeout, remaining)


def run_deadline_expired() -> bool:
    """Pollable check: has the run-level deadline already passed?

    The scheduler relies on this instead of trusting ``future.cancel()`` (which
    cannot stop an already-running Python thread) and instead of a watch-thread
    that could be starved. Returns ``False`` when no run deadline is active.
    """
    deadline = _deadline.get()
    if deadline is None:
        return False
    return deadline <= time.monotonic()
