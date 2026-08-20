"""Agent coordination core.

AgentCoordinator owns the agent registry, the shared discussion memory and
run dispatch: it creates the run trace, picks the strategy (or honors the
requested one), hands execution to ``.strategies`` and records the outcome.

Deprecated pre-1.0 methods live in ``.legacy`` and are mixed in here so old
import paths keep working. DeepseekAdapter translates harness/HTTP events
into coordinator runs.
"""
from threading import RLock
from typing import Any, Dict, List, Optional

from .agents import Agent
from .context import ContextPolicy
from .legacy import LegacyCoordinatorAPI
from .memory import MessageStore
from .observability import RunRegistry, Trace, activate_trace, restore_trace


class AgentCoordinator(LegacyCoordinatorAPI):
    """Agent registry plus strategy dispatch.

    The registry is guarded by a lock so HTTP-driven registration can happen
    concurrently with running collaborations (property access returns an
    immutable snapshot).

    Note: passing ``context``/``cache`` to :meth:`run` updates the
    coordinator-level defaults (sticky configuration), matching the
    historical behavior where a harness configures compression once and
    every later run inherits it.
    """

    def __init__(
        self,
        memory: Optional[MessageStore] = None,
        timeout: float = 15.0,
        context_policy: Optional[ContextPolicy] = None,
        cache: bool = False,
    ):
        self._agents: Dict[str, Agent] = {}
        self._lock = RLock()
        self.memory = memory if memory is not None else MessageStore()
        self.timeout = timeout
        self.context_policy = context_policy
        self.cache = bool(cache)
        self.runs = RunRegistry()

    # -- registry ---------------------------------------------------------
    def register_agent(self, agent: Agent, replace: bool = True) -> None:
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
        consensus | relay | auto. With "auto", a strategy is picked from the
        registered agents.

        Extra kwargs (rounds, judge, order, workers, timeout, ...) are
        forwarded to the strategy function. Two run-level switches are
        consumed by the coordinator itself:

        - ``context``: a ContextPolicy or dict with window/max_chars/hide_own
          keys; replaces the coordinator-level policy from this run on.
        - ``cache``: bool; enables/disables the in-process LLM response
          cache on the registered LLM agents from this run on.
        - ``session_id``: optional correlation id stamped on the run trace.
        """
        from . import strategies  # local import keeps module graph acyclic
        context = kwargs.pop("context", None)
        cache = kwargs.pop("cache", None)
        session_id = kwargs.pop("session_id", None)
        if context is not None:
            if isinstance(context, ContextPolicy):
                self.context_policy = context
            else:
                self.context_policy = ContextPolicy.from_dict(context)
        if cache is not None:
            self.cache = bool(cache)
            self._apply_cache(self.cache)
        if not self._agents:
            raise RuntimeError("no agents registered")
        if (strategy or "").lower() == "auto":
            strategy = self._auto_strategy()
        trace = Trace(prompt=prompt, strategy=strategy, session_id=session_id)
        token = activate_trace(trace)
        try:
            try:
                result = strategies.run_strategy(self, strategy, prompt, **kwargs)
            finally:
                restore_trace(token)
            trace.tasks_from_rounds(result.get("rounds") or [])
            meta = result.setdefault("meta", {}) if isinstance(result, dict) else None
            if meta is not None:
                meta["run_id"] = trace.run_id
            trace.finish()
            self.runs.record(trace)
            return result
        except BaseException as exc:
            trace.finish(error=str(exc))
            self.runs.record(trace)
            raise

    def _apply_cache(self, enabled: bool) -> None:
        """Enable/disable the in-process response cache on registered LLM agents."""
        from .agents import ResponseCache
        for agent in self.agents:
            if agent.provider is None:
                continue
            agent.cache = bool(enabled)
            if enabled and agent._cache is None:
                agent._cache = ResponseCache()

    def _auto_strategy(self) -> str:
        """Heuristic: 1 agent -> broadcast; a "supervisor" agent present
        -> supervisor; otherwise debate (2+ agents)."""
        names = self.agent_names
        if len(names) == 1:
            return "broadcast"
        if "supervisor" in names:
            return "supervisor"
        return "debate"


class DeepseekAdapter:
    """Translate harness events into AgentCoordinator runs.

    Supported events (JSON dicts):

    - {"type": "run", "prompt": str, "strategy": str, "rounds": int,
       "judge": str, "order": [names], "workers": [names], "timeout": float,
       "context": {...} (optional), "cache": bool (optional),
       "session_id": str (optional)}
    - {"type": "agents"}            -> registered agents
    - {"type": "status"}            -> status summary
    - {"type": "register", "agents": [{name, kind, ...}]}  -> register from config dicts
    - {"type": "history", "limit": int}                     -> recent run records
      (only when a RunHistory was provided at construction)

    When a ``registry`` (a SessionManager or any callable mapping session
    ids to coordinators) is provided and an event carries a ``session_id``,
    the event is routed to that session's own coordinator, giving every
    session an isolated agent registry and shared memory. Events without
    ``session_id`` keep using the default coordinator.
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
        """Append a run summary to RunHistory (when enabled); failures are skipped."""
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
            "run_id": meta.get("run_id"),
        })

    @staticmethod
    def _truncate(value: Any, limit: Optional[int]) -> Any:
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
            kwargs: Dict[str, Any] = {"session_id": event.get("session_id")}
            for key in ("rounds", "judge", "order", "workers", "timeout"):
                if event.get(key) is not None:
                    kwargs[key] = event[key]
            if event.get("context") is not None:
                kwargs["context"] = event["context"]
            if event.get("cache") is not None:
                kwargs["cache"] = event["cache"]
            result = coord.run(prompt, strategy=event.get("strategy", "auto"), **kwargs)
            self._record_history(event, result)
            return result
        if t == "agents":
            return {"agents": [a.describe() for a in coord.agents]}
        if t == "status":
            return {
                "status": "ok",
                "agents": [a.name for a in coord.agents],
                "strategy": coord._auto_strategy() if coord.agents else None,
                "runs": len(getattr(coord, "runs", ()) or ()),
            }
        if t == "register":
            from .agents import AgentFactory
            added = []
            for cfg in event.get("agents", []):
                try:
                    agent = AgentFactory.from_config(cfg)
                except Exception as exc:  # noqa: BLE001 - report config errors on the wire
                    return {"error": f"invalid agent config: {exc}"}
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
