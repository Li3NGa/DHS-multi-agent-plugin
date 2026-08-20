"""Shared bounded worker pool.

All agent calls and scheduled tasks in the process run on one bounded
ThreadPoolExecutor, so concurrency has a hard ceiling no matter how many
coordinators, sessions or strategies are active. The ceiling defaults to
16 and can be overridden with ``DSMA_MAX_CONCURRENCY``.

Python threads cannot be killed, so a timed-out call keeps occupying its
worker until its own I/O timeout fires; the pool size is the safety net
that keeps thread counts from exploding in the meantime.
"""
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

DEFAULT_MAX_WORKERS = 16

_pool: Optional[ThreadPoolExecutor] = None
_lock = threading.Lock()


def max_workers() -> int:
    raw = os.environ.get("DSMA_MAX_CONCURRENCY")
    if raw is None:
        return DEFAULT_MAX_WORKERS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_WORKERS
    return max(1, value)


def shared_executor() -> ThreadPoolExecutor:
    global _pool
    with _lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(
                max_workers=max_workers(), thread_name_prefix="dsma-worker"
            )
        return _pool


def shutdown_executor(wait: bool = False) -> None:
    """Drop the shared pool (used by tests and on graceful shutdown)."""
    global _pool
    with _lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.shutdown(wait=wait, cancel_futures=True)
