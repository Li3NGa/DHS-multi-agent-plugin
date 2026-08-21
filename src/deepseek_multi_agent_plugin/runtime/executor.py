"""Shared bounded worker pool.

All agent calls and scheduled tasks in the process run on one bounded
ThreadPoolExecutor, so concurrency has a hard ceiling no matter how many
coordinators, sessions or strategies are active. The ceiling defaults to
16 and can be overridden with ``DSMA_MAX_CONCURRENCY``.

Python threads cannot be killed. A timed-out or cancelled call therefore
keeps occupying its worker until it ends on its own — either it observes
its ``CancellationToken`` at a cooperative checkpoint (see
``context.py``), or its provider / HTTP timeout fires. ``Future.cancel()``
only prevents a future that has not started yet; it never stops a
running thread. The pool size is the safety net that keeps thread counts
bounded in the meantime.

To keep slow workers from making the queue grow without bound behind
them, the pool is wrapped in a counting gate: ``submit()`` waits at most
``DSMA_POOL_SLOT_TIMEOUT`` (default 1s) for a free worker slot and then
fails fast with :class:`PoolSaturated`. Callers treat saturation like a
timeout instead of parking an unbounded backlog in the executor queue.
"""
import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Optional

from ..exceptions import PoolSaturated

DEFAULT_MAX_WORKERS = 16
DEFAULT_SLOT_TIMEOUT = 1.0


def max_workers() -> int:
    raw = os.environ.get("DSMA_MAX_CONCURRENCY")
    if raw is None:
        return DEFAULT_MAX_WORKERS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_WORKERS
    return max(1, value)


def _slot_timeout() -> float:
    raw = os.environ.get("DSMA_POOL_SLOT_TIMEOUT")
    if raw is None:
        return DEFAULT_SLOT_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_SLOT_TIMEOUT
    return max(0.0, value)


class _BoundedExecutor:
    """A ``ThreadPoolExecutor`` with a counting gate.

    ``submit()`` acquires a slot before dispatching; the slot is released
    when the wrapped callable finishes. If no slot frees up within the
    configured wait, :class:`PoolSaturated` is raised instead of queueing
    another task behind slow workers.
    """

    def __init__(self, max_workers_: int) -> None:
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers_, thread_name_prefix="dsma-worker"
        )
        self._slots = threading.BoundedSemaphore(max_workers_)

    def submit(self, fn: Callable, /, *args, **kwargs) -> Future:
        if not self._slots.acquire(timeout=_slot_timeout()):
            raise PoolSaturated(
                f"shared worker pool is saturated "
                f"(no free slot within {_slot_timeout():.2f}s)"
            )

        def _run(*a, **kw):
            try:
                return fn(*a, **kw)
            finally:
                self._slots.release()

        try:
            return self._pool.submit(_run, *args, **kwargs)
        except BaseException:
            self._slots.release()
            raise

    def shutdown(self, wait: bool = False, cancel_futures: bool = True) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=cancel_futures)


_pool: Optional[_BoundedExecutor] = None
_lock = threading.Lock()


def shared_executor() -> _BoundedExecutor:
    global _pool
    with _lock:
        if _pool is None:
            _pool = _BoundedExecutor(max_workers())
        return _pool


def shutdown_executor(wait: bool = False) -> None:
    """Drop the shared pool (used by tests and on graceful shutdown)."""
    global _pool
    with _lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.shutdown(wait=wait, cancel_futures=True)
