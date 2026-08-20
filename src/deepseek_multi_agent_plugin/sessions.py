"""Session lifecycle management.

A session is an isolated coordinator (own agent registry and discussion
memory) addressed by a string id. SessionManager bounds their lifetime:

- ``ttl``: sessions idle for more than ttl seconds are evicted;
- ``max_sessions``: when exceeded, the least recently active sessions are
  evicted to make room.

Cleanup runs lazily on access and via :meth:`cleanup` — no background
thread, so the manager stays safe to embed anywhere.
"""
import time
from threading import Lock
from typing import Any, Callable, Dict, List, Optional

from .coordinator import AgentCoordinator


class SessionManager:
    """Map session ids to isolated coordinators with bounded lifetime."""

    def __init__(
        self,
        factory: Optional[Callable[[], AgentCoordinator]] = None,
        ttl: Optional[float] = None,
        max_sessions: Optional[int] = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._factory = factory
        self.ttl = ttl
        self.max_sessions = max_sessions
        self._clock = clock
        self._lock = Lock()
        self._sessions: Dict[str, AgentCoordinator] = {}
        self._last_active: Dict[str, float] = {}
        self._created: Dict[str, float] = {}

    def get_or_create(self, session_id: str) -> AgentCoordinator:
        with self._lock:
            coord = self._sessions.get(session_id)
            now = self._clock()
            if coord is None:
                self._evict_locked(keep=self.max_sessions - 1 if self.max_sessions else None)
                coord = self._factory() if self._factory else AgentCoordinator()
                self._sessions[session_id] = coord
                self._created[session_id] = now
            self._last_active[session_id] = now
            return coord

    def get(self, session_id: str) -> Optional[AgentCoordinator]:
        """Existing session only; does not create or touch."""
        with self._lock:
            return self._sessions.get(session_id)

    def touch(self, session_id: str) -> None:
        """Refresh a session's idle timer (no-op for unknown ids)."""
        with self._lock:
            if session_id in self._sessions:
                self._last_active[session_id] = self._clock()

    def delete(self, session_id: str) -> bool:
        with self._lock:
            existed = self._sessions.pop(session_id, None) is not None
            self._last_active.pop(session_id, None)
            self._created.pop(session_id, None)
            return existed

    def cleanup(self) -> List[str]:
        """Evict expired sessions now; returns the evicted ids."""
        with self._lock:
            return self._evict_locked(keep=self.max_sessions)

    def session_ids(self) -> List[str]:
        with self._lock:
            return list(self._sessions)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "count": len(self._sessions),
                "ttl": self.ttl,
                "max_sessions": self.max_sessions,
                "sessions": [
                    {
                        "session_id": sid,
                        "created_at": self._created.get(sid),
                        "last_active": self._last_active.get(sid),
                        "messages": len(getattr(coord, "memory", ()) or ()),
                    }
                    for sid, coord in self._sessions.items()
                ],
            }

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)

    # -- internals ----------------------------------------------------------
    def _evict_locked(self, keep: Optional[int] = None) -> List[str]:
        """Evict expired sessions, then sessions beyond ``keep`` (LRU first)."""
        now = self._clock()
        evicted: List[str] = []
        if self.ttl is not None:
            for sid in list(self._sessions):
                if now - self._last_active.get(sid, now) > self.ttl:
                    self._drop(sid)
                    evicted.append(sid)
        if keep is not None and len(self._sessions) > keep:
            # evict least recently active first
            by_age = sorted(self._sessions, key=lambda sid: self._last_active.get(sid, 0))
            for sid in by_age[: len(self._sessions) - keep]:
                self._drop(sid)
                evicted.append(sid)
        return evicted

    def _drop(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._last_active.pop(session_id, None)
        self._created.pop(session_id, None)


# Historical name: session isolation shipped as SessionRegistry in 1.0.
SessionRegistry = SessionManager
