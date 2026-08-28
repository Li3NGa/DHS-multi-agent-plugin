"""Agent coordination core.

AgentCoordinator owns the agent registry, the shared discussion memory and
run dispatch: it creates the run trace, picks the strategy (or honors the
requested one), hands execution to ``.strategies`` and records the outcome.

Deprecated pre-1.0 methods live in ``.legacy`` and are mixed in here so old
import paths keep working. DeepseekAdapter translates harness/HTTP events
into coordinator runs.
"""
import logging
from threading import BoundedSemaphore, RLock
from typing import Any, Dict, Iterable, List, Optional

from .agents import Agent
from .context import ContextPolicy
from .legacy import LegacyCoordinatorAPI
from .memory import MessageStore
from .observability import RunRegistry, Trace, activate_trace, restore_trace
from .runtime import (
    as_budget,
    end_run_budget,
    end_run_deadline,
    start_run_budget,
    start_run_deadline,
)

log = logging.getLogger("deepseek-multi-agent-plugin")

# Kinds remotely registrable by default over adapter `register` events.
# `cli` executes local commands and `http` performs server-side requests:
# both require explicit opt-in on the adapter (secure-by-default).
DEFAULT_REGISTER_KINDS = frozenset({"mock", "echo", "deepseek", "openai"})
_OPT_IN_REGISTER_KINDS = frozenset({"cli", "http", "custom", "fallback"})


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
        budget: Optional[Dict[str, Any]] = None,
    ):
        self._agents: Dict[str, Agent] = {}
        self._lock = RLock()
        self.memory = memory if memory is not None else MessageStore()
        self.timeout = timeout
        self.context_policy = context_policy
        self.cache = bool(cache)
        self.default_budget = budget
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
        forwarded to the strategy function. Run-level switches consumed by
        the coordinator itself:

        - ``timeout``: per-agent-call timeout; defaults to the coordinator's
          own ``timeout`` (15s), so a run never waits on a hung agent forever.
        - ``run_timeout``: budget for the whole run. Once spent, no new agent
          call or task is dispatched and RunTimeout aborts the run.
        - ``budget``: BudgetManager or dict with max_calls / max_tokens /
          max_cost / max_seconds / pricer. Every agent call reserves one
          slot up front; a spent budget raises BudgetExceeded. max_seconds
          is wall-clock and flows into the run deadline (RunTimeout). The
          final usage snapshot lands in ``meta["budget"]``. When absent,
          the coordinator's ``budget`` constructor defaults are applied
          fresh to every run.
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
        run_timeout = kwargs.pop("run_timeout", None)
        budget_opt = kwargs.pop("budget", None)
        if budget_opt is None and self.default_budget is not None:
            budget_opt = dict(self.default_budget)
        budget = as_budget(budget_opt)
        if budget is not None and budget.max_seconds is not None:
            run_timeout = (
                budget.max_seconds
                if run_timeout is None
                else min(run_timeout, budget.max_seconds)
            )
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
        kwargs.setdefault("timeout", self.timeout)
        trace = Trace(prompt=prompt, strategy=strategy, session_id=session_id)
        token = activate_trace(trace)
        deadline_token = start_run_deadline(run_timeout)
        budget_token = start_run_budget(budget)
        try:
            try:
                result = strategies.run_strategy(self, strategy, prompt, **kwargs)
            finally:
                end_run_budget(budget_token)
                end_run_deadline(deadline_token)
                restore_trace(token)
            trace.tasks_from_rounds(result.get("rounds") or [])
            meta = result.setdefault("meta", {}) if isinstance(result, dict) else None
            if meta is not None:
                meta["run_id"] = trace.run_id
                if budget is not None:
                    meta["budget"] = budget.snapshot()
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
       "run_timeout": float,
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

    ``max_concurrent_runs`` caps how many run events execute at once: a
    bounded semaphore makes an overloaded server fail fast with a clear
    error instead of exhausting the shared worker pool or the upstream LLM
    quota. ``MAX_REGISTER_AGENTS`` caps how many agents one register event
    may add, so a single (authorized) request cannot balloon memory.
    """

    MAX_REGISTER_AGENTS = 100

    def __init__(
        self,
        coordinator: AgentCoordinator,
        registry=None,
        history=None,
        history_prompt_limit: Optional[int] = None,
        history_final_limit: Optional[int] = None,
        max_concurrent_runs: int = 4,
        run_gate_timeout: float = 1.0,
        allowed_register_kinds: Optional[Iterable[str]] = None,
    ):
        self.coordinator = coordinator
        self.registry = registry
        self.history = history
        self.history_prompt_limit = history_prompt_limit
        self.history_final_limit = history_final_limit
        self.max_concurrent_runs = max(1, int(max_concurrent_runs))
        self._run_gate_timeout = max(0.0, float(run_gate_timeout))
        self._run_gate = BoundedSemaphore(self.max_concurrent_runs)
        self.allowed_register_kinds: frozenset = (
            frozenset(allowed_register_kinds)
            if allowed_register_kinds is not None
            else DEFAULT_REGISTER_KINDS
        )

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
            for key in ("rounds", "judge", "order", "workers", "timeout", "run_timeout", "budget"):
                if event.get(key) is not None:
                    kwargs[key] = event[key]
            if event.get("context") is not None:
                kwargs["context"] = event["context"]
            if event.get("cache") is not None:
                kwargs["cache"] = event["cache"]
            # 并发 run 限流：semaphore 满则快速失败（http 层映射为 429），
            # 保护共享线程池与上游 LLM 配额。
            if not self._run_gate.acquire(timeout=self._run_gate_timeout):
                return {"error": "too many concurrent runs"}
            try:
                result = coord.run(prompt, strategy=event.get("strategy", "auto"), **kwargs)
            finally:
                self._run_gate.release()
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
            agent_configs = event.get("agents", [])
            if len(agent_configs) > self.MAX_REGISTER_AGENTS:
                return {"error": f"too many agents (max {self.MAX_REGISTER_AGENTS})"}
            # Gate restricted kinds BEFORE building anything, so a restricted
            # kind can never be smuggled through as a different kind later.
            # cli executes local commands; http performs server-side requests.
            for cfg in agent_configs:
                declared = str(
                    (cfg if isinstance(cfg, dict) else {}).get("kind") or ""
                ).strip().lower()
                if (
                    declared in _OPT_IN_REGISTER_KINDS
                    and declared not in self.allowed_register_kinds
                ):
                    log.warning("register denied kind '%s' (not opted in)", declared)
                    return {
                        "error": (
                            f"agent kind '{declared}' requires explicit opt-in on "
                            f"this adapter (default-allowed kinds: "
                            f"{sorted(DEFAULT_REGISTER_KINDS)})"
                        )
                    }
            # Atomic registration: build everything first; only touch the
            # registry when every config is valid. Raw error text stays in
            # the server log, never on the wire.
            built = []
            for cfg in agent_configs:
                try:
                    built.append(AgentFactory.from_config(cfg))
                except Exception as exc:  # noqa: BLE001 - sanitized for the wire
                    log.warning("register rejected invalid config: %s", exc)
                    return {"error": "invalid agent config (details logged)"}
            registered = []
            for agent in built:
                coord.register_agent(agent)
                registered.append(agent.name)
            return {"registered": registered}
        if t == "history":
            if self.history is None:
                return {"records": [], "enabled": False}
            try:
                limit = int(event.get("limit") or 20)
            except (TypeError, ValueError):
                limit = 20
            return {"records": self.history.recent(limit)}
        return {"error": f"unsupported event type: {t}"}
