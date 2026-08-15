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
    """

    def __init__(self, capacity: Optional[int] = None):
        self.capacity = capacity
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
            if self.capacity and len(self._messages) > self.capacity:
                self._messages = self._messages[-self.capacity:]
        return msg

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
