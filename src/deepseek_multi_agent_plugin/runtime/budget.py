"""Run-level execution budgets: agent calls, tokens, cost.

A run started with ``budget=`` gets a fresh :class:`BudgetManager`. Every
agent call reserves one slot up front (``reserve``) and settles its actual
usage afterwards (``settle``); the reservation is atomic, so parallel
workers cannot both claim the last call. Token and cost limits are checked
at reservation time against what has been settled so far — the final call
may overshoot them by its own usage, since token counts are only known
after the reply arrives.

``max_seconds`` is wall-clock budget and intentionally flows into the run
deadline machinery (RunTimeout) instead of being checked here: one wall
clock, one exception type.
"""
import time
from contextvars import ContextVar
from threading import Lock
from typing import Any, Callable, Dict, Optional

from ..exceptions import BudgetExceeded


class BudgetManager:
    def __init__(
        self,
        max_calls: Optional[int] = None,
        max_tokens: Optional[int] = None,
        max_cost: Optional[float] = None,
        max_seconds: Optional[float] = None,
        pricer: Optional[Callable[[Dict[str, int]], float]] = None,
    ):
        self.max_calls = max_calls
        self.max_tokens = max_tokens
        self.max_cost = max_cost
        self.max_seconds = max_seconds
        self._pricer = pricer
        self._lock = Lock()
        self._start = time.monotonic()
        self._calls = 0
        self._reserved = 0
        self._tokens = 0
        self._cost = 0.0

    def reserve(self) -> None:
        """Atomically claim one agent call slot.

        Raises BudgetExceeded when any tracked limit is already exhausted,
        so a spent budget stops the run before new work is dispatched.
        """
        with self._lock:
            if self.max_calls is not None and self._calls + self._reserved >= self.max_calls:
                raise BudgetExceeded(f"call budget exhausted ({self._calls + self._reserved}/{self.max_calls} calls)")
            if self.max_tokens is not None and self._tokens >= self.max_tokens:
                raise BudgetExceeded(f"token budget exhausted ({self._tokens}/{self.max_tokens} tokens)")
            if self.max_cost is not None and self._cost >= self.max_cost:
                raise BudgetExceeded(f"cost budget exhausted ({self._cost:.6f}/{self.max_cost:.6f})")
            self._reserved += 1

    def settle(self, usage: Optional[Dict[str, int]] = None) -> None:
        """Account one finished call: consumes a reservation and adds the
        call's token usage and cost (via ``pricer`` when provided)."""
        tokens = 0
        cost = 0.0
        if usage:
            tokens = int(usage.get("total_tokens") or 0)
            if self._pricer is not None:
                cost = float(self._pricer(usage))
        with self._lock:
            self._calls += 1
            self._reserved = max(0, self._reserved - 1)
            self._tokens += tokens
            self._cost += cost

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            elapsed = time.monotonic() - self._start
            return {
                "calls": self._calls,
                "in_flight": self._reserved,
                "tokens": self._tokens,
                "cost": round(self._cost, 6),
                "elapsed_seconds": round(elapsed, 3),
                "limits": {
                    "max_calls": self.max_calls,
                    "max_tokens": self.max_tokens,
                    "max_cost": self.max_cost,
                    "max_seconds": self.max_seconds,
                },
            }


def as_budget(value: Any) -> Optional[BudgetManager]:
    """Coerce ``budget=`` run options into a BudgetManager.

    Accepts None, a BudgetManager (used as-is, so callers can share one
    budget across runs) or a dict with max_calls / max_tokens / max_cost /
    max_seconds / pricer keys.
    """
    if value is None or isinstance(value, BudgetManager):
        return value
    if isinstance(value, dict):
        known = {"max_calls", "max_tokens", "max_cost", "max_seconds", "pricer"}
        unknown = set(value) - known
        if unknown:
            raise ValueError(f"unknown budget options: {sorted(unknown)}")
        limits = dict(value)
        # 负数上限会让预算立即“耗尽”，且语义含糊（如 max_calls=-5 直接拦截
        # 一切调用）——在入口统一拒绝，把错误暴露给调用方而不是运行时。
        for key in ("max_calls", "max_tokens"):
            v = limits.get(key)
            if v is not None and int(v) < 0:
                raise ValueError(f"{key} must be >= 0")
        for key in ("max_cost", "max_seconds"):
            v = limits.get(key)
            if v is not None and float(v) < 0:
                raise ValueError(f"{key} must be >= 0")
        return BudgetManager(**limits)
    raise ValueError("budget must be a BudgetManager or a dict of limits")


_budget: ContextVar[Optional[BudgetManager]] = ContextVar("dsma_run_budget", default=None)


def start_run_budget(budget: Optional[BudgetManager]):
    """Install the run budget; returns a token for :func:`end_run_budget`."""
    if budget is None:
        return None
    return _budget.set(budget)


def end_run_budget(token) -> None:
    if token is not None:
        _budget.reset(token)


def current_budget() -> Optional[BudgetManager]:
    return _budget.get()
