"""In-process LLM response cache: LRU eviction, TTL, statistics."""
import hashlib
import json
import time
from collections import OrderedDict
from threading import Lock
from typing import Any, Dict, Optional, Tuple


def request_fingerprint(**fields: Any) -> str:
    """Stable sha256 digest over every request parameter that can change the
    model's reply (provider/base_url, model, messages, sampling options,
    response_format, tools, seed, ...).

    Transport-only options (timeout, retries, api_key) are deliberately
    excluded: they cannot change the answer, and the digest must stay stable
    across processes and restarts.
    """
    blob = json.dumps(fields, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ResponseCache:
    """Thread-safe in-process LRU cache for LLM responses.

    ``maxsize`` bounds the entry count (least-recently-used entries are
    evicted first); ``ttl`` expires entries lazily on read. ``stats()``
    reports hits / misses / expirations / evictions so callers can see
    whether the cache is actually paying off.
    """

    def __init__(self, maxsize: int = 128, ttl: Optional[float] = None, clock=time.monotonic):
        self.maxsize = max(1, int(maxsize))
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be positive (or None to disable expiry)")
        self.ttl = float(ttl) if ttl is not None else None
        self._clock = clock
        self._data: "OrderedDict[str, Tuple[str, Optional[float]]]" = OrderedDict()
        self._lock = Lock()
        self._hits = 0
        self._misses = 0
        self._expired = 0
        self._evictions = 0

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return None
            value, expires_at = entry
            if expires_at is not None and self._clock() >= expires_at:
                del self._data[key]
                self._expired += 1
                self._misses += 1
                return None
            self._data.move_to_end(key)
            self._hits += 1
            return value

    def put(self, key: str, value: str) -> None:
        expires_at = self._clock() + self.ttl if self.ttl is not None else None
        with self._lock:
            self._data[key] = (value, expires_at)
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)
                self._evictions += 1

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "size": len(self._data),
                "maxsize": self.maxsize,
                "ttl": self.ttl,
                "hits": self._hits,
                "misses": self._misses,
                "expired": self._expired,
                "evictions": self._evictions,
            }

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
