"""Agent coordination primitives and the DeepSeek harness adapter.

AgentCoordinator owns the agent registry and the shared discussion memory,
and dispatches tasks to the collaboration strategies implemented in
``.strategies`` (broadcast, sequential, debate, supervisor, consensus).

DeepseekAdapter translates harness/HTTP events into coordinator runs so
external systems (e.g. the DeepSeek Harness) can drive the plugin over
JSON without importing this package.
"""
from threading import RLock
from typing import Any, Dict, List, Optional

from .agents import Agent
from .memory import MessageStore


class AgentCoordinator:
    """Registry of agents plus the shared memory and strategy dispatch.

    The registry is guarded by a lock so HTTP-driven registration can happen
    concurrently with running collaborations (property access returns an
    immutable snapshot).
    """

    def __init__(self, memory: Optional[MessageStore] = None, timeout: float = 15.0):
        self._agents: Dict[str, Agent] = {}
        self._lock = RLock()
        self.memory = memory if memory is not None else MessageStore()
        self.timeout = timeout

    # -- registry ---------------------------------------------------------
    def register_agent(self, agent: Agent, replace: bool = True) -> None:
        """Register an agent; optionally replace an existing one with the
        same name."""
        with self._lock:
            if agent.name in self._agents and not replace:
                raise ValueError(f"agent '{agent.name}' already registered")
            self._agents[agent.name] = agent

    def unregister_agent(self, name: str) -> None:
        with self._lock:
            self._agents.pop(name, None)

    def get_agent(self, name: str) -> Optional[Agent]:
        with self._lock:
            return self._agents.get(name)

    @property
    def agents(self) -> List[Agent]:
        """Agents in registration order (snapshot copy)."""
        with self._lock:
            return list(self._agents.values())

    @property
    def agent_names(self) -> List[str]:
        with self._lock:
            return list(self._agents.keys())

    def __len__(self) -> int:
        with self._lock:
            return len(self._agents)

    # -- execution ---------------------------------------------------------
    def run(self, prompt: str, strategy: str = "auto", **kwargs: Any) -> Dict[str, Any]:
        """Run a collaborative task with the named strategy.

        strategy: one of broadcast | sequential | debate | supervisor |
        consensus | auto. With "auto", a strategy is picked from the
        registered agents (see _auto_strategy).

        Extra kwargs (rounds, judge, order, workers, timeout, ...) are
        forwarded to the strategy function.
        """
        from . import strategies  # local import keeps module graph acyclic
        if not self._agents:
            raise RuntimeError("no agents registered")
        if (strategy or "").lower() == "auto":
            strategy = self._auto_strategy()
        return strategies.run_strategy(self, strategy, prompt, **kwargs)

    def _auto_strategy(self) -> str:
        """Heuristic: 1 agent -> broadcast; a "supervisor" agent present
        -> supervisor; otherwise debate (2+ agents)."""
        names = self.agent_names
        if len(names) == 1:
            return "broadcast"
        if "supervisor" in names:
            return "supervisor"
        return "debate"

    # -- backward-compatible helpers ----------------------------------------
    def broadcast(self, message: Any, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Legacy: ask every agent in parallel for a single message."""
        from .strategies import _parallel
        return _parallel(self, message, timeout=timeout if timeout is not None else self.timeout)

    def run_cooperative_task(self, initial_prompt: str, rounds: int = 3) -> List[Dict[str, Any]]:
        """Legacy API kept for compatibility: same as ``run(..., strategy="broadcast")``.
        Returns the list of round records."""
        result = self.run(initial_prompt, strategy="broadcast", rounds=rounds,
                          timeout=self.timeout)
        return result["rounds"]


class DeepseekAdapter:
    """Translate harness events into AgentCoordinator runs.

    Supported events (JSON dicts):

    - {"type": "run", "prompt": str, "strategy": str, "rounds": int,
       "judge": str, "order": [names], "workers": [names], "timeout": float,
       "session_id": str (optional)}
    - {"type": "agents"}            -> registered agents
    - {"type": "status"}            -> status summary
    - {"type": "register", "agents": [{name, kind, ...}]}  -> register from config dicts
    - {"type": "history", "limit": int}                     -> recent run records
      (only when a RunHistory was provided at construction)

    When a ``registry`` (a SessionRegistry or any callable mapping
    session ids to coordinators) is provided and an event carries a
    ``session_id``, the event is routed to that session's own coordinator,
    giving every session an isolated agent registry and shared memory.
    Events without ``session_id`` keep using the default coordinator.
    """

    def __init__(
        self,
        coordinator: AgentCoordinator,
        registry=None,
        history=None,
        history_prompt_limit: Optional[int] = None,
        history_final_limit: Optional[int] = None,
    ):
        self.coordinator = coordinator
        self.registry = registry
        self.history = history
        self.history_prompt_limit = history_prompt_limit
        self.history_final_limit = history_final_limit

    def _coordinator_for(self, event: Dict[str, Any]) -> AgentCoordinator:
        session_id = event.get("session_id")
        if session_id and self.registry is not None:
            return self.registry.get_or_create(session_id)
        return self.coordinator

    def _record_history(self, event: Dict[str, Any], result: Dict[str, Any]) -> None:
        """run 成功后把结果摘要写入 RunHistory（若启用）；失败不记录。"""
        if self.history is None or not isinstance(result, dict) or "error" in result:
            return
        meta = result.get("meta") or {}
        prompt = result.get("prompt", event.get("prompt", ""))
        final = result.get("final")
        prompt = self._truncate(prompt, self.history_prompt_limit)
        final = self._truncate(final, self.history_final_limit)
        self.history.append({
            "strategy": result.get("strategy"),
            "prompt": prompt,
            "final": final,
            "rounds": len(result.get("rounds") or []),
            "session_id": event.get("session_id"),
            "elapsed_seconds": meta.get("elapsed_seconds"),
        })

    @staticmethod
    def _truncate(value: Any, limit: Optional[int]) -> Any:
        """Truncate string fields for privacy/volume control (None = keep as-is)."""
        if limit is None or not isinstance(value, str):
            return value
        limit = max(0, int(limit))
        if limit == 0:
            return ""
        if len(value) <= limit:
            return value
        return value[:limit] + "…"

    def handle_harness_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        t = event.get("type")
        coord = self._coordinator_for(event)
        if t == "run":
            prompt = event.get("prompt", "")
            if not prompt:
                return {"error": "missing prompt"}
            kwargs: Dict[str, Any] = {}
            for key in ("rounds", "judge", "order", "workers", "timeout"):
                if event.get(key) is not None:
                    kwargs[key] = event[key]
            result = coord.run(
                prompt,
                strategy=event.get("strategy", "auto"),
                **kwargs,
            )
            self._record_history(event, result)
            return result
        if t == "agents":
            return {"agents": [a.describe() for a in coord.agents]}
        if t == "status":
            return {
                "status": "ok",
                "agents": [a.name for a in coord.agents],
                "strategy": coord._auto_strategy() if coord.agents else None,
            }
        if t == "register":
            from .agents import AgentFactory
            added = []
            for cfg in event.get("agents", []):
                agent = AgentFactory.from_config(cfg)
                coord.register_agent(agent)
                added.append(agent.name)
            return {"registered": added}
        if t == "history":
            if self.history is None:
                return {"records": [], "enabled": False}
            try:
                limit = int(event.get("limit") or 20)
            except (TypeError, ValueError):
                limit = 20
            return {"records": self.history.recent(limit)}
        return {"error": f"unsupported event type: {t}"}
