"""Shared conversation memory for multi-agent collaboration.

MessageStore is a lightweight, thread-safe append-only message buffer used by
the coordinator and the strategies to give every agent a view of the ongoing
discussion (broadcast rounds, debate statements, supervisor reports, ...).
"""
from threading import Lock
from typing import Any, Dict, List, Optional


class MessageStore:
    """Ordered, optionally capacity-bounded conversation memory.

    Each message is a dict: {"role", "content", "agent", ...meta}.
    role is one of "user" | "assistant" | "system".

    Two independent bounds keep long-lived coordinators from growing
    forever: ``capacity`` (max message count) and ``max_chars`` (total
    content budget; oldest messages are dropped first, the newest message
    is always kept). ``ContextPolicy`` controls what each agent *sees*
    per request; these bounds control what is *stored*.
    """

    def __init__(self, capacity: Optional[int] = None, max_chars: Optional[int] = None):
        self.capacity = capacity
        self.max_chars = max_chars
        self._messages: List[Dict[str, Any]] = []
        self._lock = Lock()

    def add(
        self,
        role: str,
        content: Any,
        agent: Optional[str] = None,
        **meta: Any,
    ) -> Dict[str, Any]:
        """Append a message and return it."""
        msg: Dict[str, Any] = {"role": role, "content": content, "agent": agent}
        msg.update(meta)
        with self._lock:
            self._messages.append(msg)
            self._enforce_locked()
        return msg

    def _enforce_locked(self) -> None:
        if self.capacity and len(self._messages) > self.capacity:
            self._messages = self._messages[-self.capacity:]
        if self.max_chars is not None:
            total = sum(len(str(m.get("content", ""))) for m in self._messages)
            while len(self._messages) > 1 and total > self.max_chars:
                total -= len(str(self._messages[0].get("content", "")))
                self._messages.pop(0)

    def chars(self) -> int:
        """Total stored content size (for capacity statistics)."""
        with self._lock:
            return sum(len(str(m.get("content", ""))) for m in self._messages)

    def all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._messages)

    def recent(self, n: int) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._messages[-n:])

    def clear(self) -> None:
        with self._lock:
            self._messages.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._messages)

    def to_chat(
        self,
        limit: Optional[int] = None,
        with_speaker: bool = False,
    ) -> List[Dict[str, str]]:
        """Project messages into OpenAI-style chat format [{role, content}].

        Only user/assistant/system messages are included. With
        ``with_speaker=True``, assistant messages produced by a named agent
        are prefixed with ``[agent_name]: `` so LLM participants can tell
        who said what in a shared discussion.
        """
        msgs = self.all() if limit is None else self.recent(limit)
        out = []
        for m in msgs:
            role = m.get("role")
            if role not in ("user", "assistant", "system"):
                continue
            content = str(m.get("content", ""))
            if with_speaker and role == "assistant" and m.get("agent"):
                content = f"[{m['agent']}]: {content}"
            out.append({"role": role, "content": content})
        return out
