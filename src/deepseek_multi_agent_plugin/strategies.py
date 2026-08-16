"""Multi-agent collaboration strategies.

Every strategy is a function ``fn(coordinator, prompt, **opts) -> dict`` with
the same result shape:

    {
        "strategy": str,
        "prompt": str,
        "rounds": [step records...],
        "final": str,          # final answer
        "meta": {elapsed_seconds, agents},
    }
Strategies share a coordinator-level MessageStore as the discussion memory,
so every agent sees the ongoing transcript (via ``context`` for LLM agents).
"""
import inspect
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, Dict, List, Optional, Sequence


def _call_agent(agent, message, context=None, timeout=None):
    """Call one agent; exceptions are returned as {"error": ...} dicts.

    On timeout the executor is shut down without waiting, so a hung agent
    never blocks the strategy thread past its timeout (the worker thread
    itself keeps running until the agent's own HTTP timeout fires).
    """
    if timeout is None:
        try:
            return agent.handle(message, context)
        except Exception as e:  # noqa: BLE001 - strategy-level resilience
            return {"error": str(e)}
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        fut = ex.submit(agent.handle, message, context)
        return fut.result(timeout=timeout)
    except (TimeoutError, FuturesTimeoutError):
        return {"error": "timeout"}
    except Exception as e:  # noqa: BLE001 - strategy-level resilience
        return {"error": str(e)}
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def _parallel(coord, message, agents=None, context=None, timeout=None) -> Dict[str, Any]:
    """Ask every agent in parallel; errors are captured per agent."""
    targets = agents if agents is not None else coord.agents
    results: Dict[str, Any] = {}
    ex = ThreadPoolExecutor(max_workers=max(1, len(targets)))
    futures = {ex.submit(_call_agent, a, message, context, timeout): a.name for a in targets}
    try:
        for f in as_completed(futures, timeout=timeout):
            results[futures[f]] = f.result()
    except (TimeoutError, FuturesTimeoutError):
        pass  # remaining agents are marked below
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    for a in targets:
        results.setdefault(a.name, {"error": "timeout"})
    return results


def _is_error(value: Any) -> bool:
    return isinstance(value, dict) and "error" in value


def _join(responses: Dict[str, Any], fallback: str = "") -> str:
    parts = [str(v) for v in responses.values() if not _is_error(v)]
    return "\n\n".join(parts) if parts else fallback


def _format_statements(responses: Dict[str, Any]) -> str:
    return "\n\n".join(f"[{n}]: {v}" for n, v in responses.items() if not _is_error(v))


def _record(coord, role: str, content: Any, agent: Optional[str] = None):
    coord.memory.add(role, content, agent=agent)


def _meta(coord, start: float, strategy: str) -> Dict[str, Any]:
    usage = {
        a.name: dict(a.total_usage)
        for a in coord.agents
        if getattr(a, "total_usage", {}).get("total_tokens")
    }
    meta: Dict[str, Any] = {
        "elapsed_seconds": round(time.time() - start, 3),
        "agents": [a.name for a in coord.agents],
        "strategy": strategy,
    }
    if usage:
        meta["usage"] = usage
    return meta


# --------------------------------------------------------------------------
# broadcast: parallel round-robin discussion
# --------------------------------------------------------------------------
def run_broadcast(coord, prompt: str, rounds: int = 1, timeout: Optional[float] = None) -> Dict[str, Any]:
    """All agents answer in parallel; with rounds > 1 the joined answers are
    fed back as the next round input."""
    start = time.time()
    records = []
    last = prompt
    _record(coord, "user", prompt)
    for r in range(1, max(1, int(rounds)) + 1):
        responses = _parallel(coord, last, timeout=timeout)
        for name, resp in responses.items():
            if not _is_error(resp):
                _record(coord, "assistant", resp, agent=name)
        records.append({"round": r, "kind": "broadcast", "responses": responses})
        last = _join(responses, fallback=last)
    return {
        "strategy": "broadcast",
        "prompt": prompt,
        "rounds": records,
        "final": last,
        "meta": _meta(coord, start, "broadcast"),
    }


# --------------------------------------------------------------------------
# sequential: chain-of-agents
# --------------------------------------------------------------------------
def run_sequential(
    coord,
    prompt: str,
    order: Optional[Sequence[str]] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Agents respond one after another in the given order (or registration
    order); each agent sees the full transcript produced so far."""
    start = time.time()
    names = [a.name for a in coord.agents] if not order else list(order)
    missing = [n for n in names if coord.get_agent(n) is None]
    if missing:
        raise ValueError(f"sequential: unknown agents in order: {missing}")
    records = []
    transcript = str(prompt)
    _record(coord, "user", prompt)
    for i, name in enumerate(names, 1):
        resp = _call_agent(coord.get_agent(name), transcript, timeout=timeout)
        if not _is_error(resp):
            _record(coord, "assistant", resp, agent=name)
        records.append({"step": i, "agent": name, "response": resp})
        transcript = f"{transcript}\n\n[{name}]: {resp}"
    final = records[-1]["response"] if records else prompt
    return {
        "strategy": "sequential",
        "prompt": prompt,
        "rounds": records,
        "final": str(final),
        "meta": _meta(coord, start, "sequential"),
    }


# --------------------------------------------------------------------------
# debate: argue, then a judge synthesizes
# --------------------------------------------------------------------------
def run_debate(
    coord,
    prompt: str,
    rounds: int = 3,
    judge: Optional[str] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Agents debate for ``rounds`` rounds (each round everyone sees the
    transcript so far). Then the judge agent (or the first agent when no
    judge is named) produces the final synthesis."""
    start = time.time()
    records = []
    names = [a.name for a in coord.agents]
    if len(names) < 2:
        raise ValueError("debate needs at least two agents")
    _record(coord, "user", prompt)
    last_responses = {}
    for r in range(1, max(1, int(rounds)) + 1):
        context = coord.memory.to_chat(with_speaker=True)
        responses = _parallel(coord, prompt, context=context, timeout=timeout)
        for name, resp in responses.items():
            if not _is_error(resp):
                _record(coord, "assistant", resp, agent=name)
        records.append({"round": r, "kind": "debate", "responses": responses})
        last_responses = responses
    judge_name = judge or ("judge" if "judge" in names else names[0])
    judge_agent = coord.get_agent(judge_name)
    if judge_agent is None:
        raise ValueError(f"debate: judge agent '{judge_name}' not registered")
    judge_input = f"{prompt}\n\n以下是各位辩手的观点:\n{_format_statements(last_responses)}\n\n" "请以裁判身份综合所有观点，给出最终结论与理由。"
    final = _call_agent(judge_agent, judge_input, timeout=timeout)
    if not _is_error(final):
        _record(coord, "assistant", final, agent=judge_name)
    records.append({"step": "judge", "agent": judge_name, "response": final})
    return {
        "strategy": "debate",
        "prompt": prompt,
        "rounds": records,
        "final": str(final),
        "meta": _meta(coord, start, "debate"),
    }


# --------------------------------------------------------------------------
# supervisor: decompose -> delegate -> synthesize
# --------------------------------------------------------------------------
def run_supervisor(
    coord,
    prompt: str,
    supervisor: Optional[str] = None,
    workers: Optional[Sequence[str]] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """The supervisor decomposes the task into one-subtask-per-line, workers
    (round-robin) solve the subtasks in parallel, and the supervisor writes
    the final report from the worker results."""
    start = time.time()
    names = [a.name for a in coord.agents]
    sup_name = supervisor or ("supervisor" if "supervisor" in names else names[0])
    sup = coord.get_agent(sup_name)
    if sup is None:
        raise ValueError(f"supervisor: agent '{sup_name}' not registered")
    worker_names = list(workers) if workers else [n for n in names if n != sup_name]
    if not worker_names:
        raise ValueError("supervisor strategy needs at least one worker besides the supervisor")
    missing = [n for n in worker_names if coord.get_agent(n) is None]
    if missing:
        raise ValueError(f"supervisor: unknown worker agents: {missing}")

    records = []
    _record(coord, "user", prompt)

    # 1) plan
    plan = _call_agent(
        sup,
        f"{prompt}\n\n请把上面的任务分解为多个子任务，每行一个子任务，只输出子任务列表。",
        timeout=timeout,
    )
    if not _is_error(plan):
        _record(coord, "assistant", plan, agent=sup_name)
    records.append({"step": "plan", "agent": sup_name, "response": plan})
    subtasks = [ln.strip() for ln in str(plan).splitlines() if ln.strip()]
    if not subtasks:
        subtasks = [str(prompt)]

    # 2) delegate round-robin and solve in parallel
    assigned: Dict[str, List[str]] = {}
    for i, sub in enumerate(subtasks):
        assigned.setdefault(worker_names[i % len(worker_names)], []).append(sub)
    results: Dict[str, Any] = {}
    ex = ThreadPoolExecutor(max_workers=max(1, len(assigned)))
    futures = {
        ex.submit(_call_agent, coord.get_agent(w), "\n".join(tasks), None, timeout): w
        for w, tasks in assigned.items()
    }
    try:
        for f in as_completed(futures, timeout=timeout):
            results[futures[f]] = f.result()
    except (TimeoutError, FuturesTimeoutError):
        pass
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    for w in assigned:
        results.setdefault(w, {"error": "timeout"})
    for name, resp in results.items():
        if not _is_error(resp):
            _record(coord, "assistant", resp, agent=name)
    records.append({"step": "work", "subtasks": subtasks, "assigned": assigned, "results": results})

    # 3) final report
    report = _call_agent(
        sup,
        f"{prompt}\n\n子任务完成情况:\n{_format_statements(results)}\n\n请综合所有子任务结果，给出最终的完整回答。",
        timeout=timeout,
    )
    if not _is_error(report):
        _record(coord, "assistant", report, agent=sup_name)
    records.append({"step": "report", "agent": sup_name, "response": report})
    return {
        "strategy": "supervisor",
        "prompt": prompt,
        "rounds": records,
        "final": str(report),
        "meta": _meta(coord, start, "supervisor"),
    }


# --------------------------------------------------------------------------
# relay: pass-the-baton draft refinement
# --------------------------------------------------------------------------
def run_relay(
    coord,
    prompt: str,
    rounds: int = 2,
    order: Optional[Sequence[str]] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Agents polish the same draft in turns, each one seeing the previous
    output; every agent taking the baton once counts as one round. The run
    stops early as soon as a round leaves the draft unchanged.
    """
    start = time.time()
    names = [a.name for a in coord.agents] if not order else list(order)
    if len(names) < 2:
        raise ValueError("relay needs at least two agents")
    missing = [n for n in names if coord.get_agent(n) is None]
    if missing:
        raise ValueError(f"relay: unknown agents in order: {missing}")
    records = []
    draft = str(prompt)
    _record(coord, "user", prompt)
    for r in range(1, max(1, int(rounds)) + 1):
        round_start = draft
        steps = []
        for i, name in enumerate(names, 1):
            message = (
                f"原始任务：{prompt}\n\n当前草稿：\n{draft}\n\n"
                "要求：请改进下面这份草稿，只输出改进后的完整草稿。"
            )
            resp = _call_agent(coord.get_agent(name), message, timeout=timeout)
            if not _is_error(resp):
                draft = str(resp)
                _record(coord, "assistant", draft, agent=name)
            steps.append({"step": i, "agent": name, "response": resp})
        # 每轮的轮初草稿即上一轮的轮末草稿，因此"与轮初相同"同时覆盖
        # "连续两轮无变化"的收敛条件，无需单独跟踪上一轮。
        converged = draft == round_start
        records.append({"round": r, "kind": "relay", "steps": steps, "converged": converged})
        if converged:
            break
    return {
        "strategy": "relay",
        "prompt": prompt,
        "rounds": records,
        "final": draft,
        "meta": _meta(coord, start, "relay"),
    }


# --------------------------------------------------------------------------
# consensus: propose -> vote (majority) -> final
# --------------------------------------------------------------------------
def _parse_vote(text: str, candidates: Sequence[str]) -> Optional[str]:
    """Extract the voted candidate name from a free-form vote text."""
    low = str(text).strip().lower()
    for c in candidates:
        if low == c.lower() or low == f"vote:{c.lower()}" or low == f"vote: {c.lower()}":
            return c
    for c in candidates:  # fall back to substring match
        if f"vote:{c.lower()}" in low or f"vote: {c.lower()}" in low:
            return c
    return None


def run_consensus(
    coord,
    prompt: str,
    judge: Optional[str] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Each agent proposes an answer; then everyone votes for the best
    proposal (majority wins). On a tie, the judge agent (or first agent)
    picks the winner."""
    start = time.time()
    names = [a.name for a in coord.agents]
    if len(names) < 2:
        raise ValueError("consensus needs at least two agents")
    records = []
    _record(coord, "user", prompt)

    proposals = _parallel(coord, prompt, timeout=timeout)
    for name, resp in proposals.items():
        if not _is_error(resp):
            _record(coord, "assistant", resp, agent=name)
    records.append({"step": "propose", "responses": proposals})

    ballot = _format_statements(proposals)
    vote_prompt = f"{prompt}\n\n候选方案:\n{ballot}\n\n请投票选出最佳方案，输出格式: vote:<agent_name>"
    votes = _parallel(coord, vote_prompt, timeout=timeout)
    records.append({"step": "vote", "votes": votes})

    counts: Counter = Counter()
    for name, v in votes.items():
        w = _parse_vote(v, names)
        if w:
            counts[w] += 1
    winner: Optional[str] = None
    if counts:
        top = counts.most_common()
        if len(top) == 1 or top[0][1] > top[1][1]:
            winner = top[0][0]

    if winner is not None and not _is_error(proposals.get(winner)):
        final = proposals[winner]
        records.append({"step": "final", "winner": winner, "votes": dict(counts), "response": final})
    else:
        judge_name = judge or ("judge" if "judge" in names else names[0])
        judge_agent = coord.get_agent(judge_name)
        verdict = _call_agent(
            judge_agent,
            f"{vote_prompt}\n\n请作为裁判，综合所有方案与投票，直接给出最终答案。",
            timeout=timeout,
        )
        if not _is_error(verdict):
            _record(coord, "assistant", verdict, agent=judge_name)
        records.append({"step": "final", "judge": judge_name, "votes": dict(counts), "response": verdict})
        final = verdict
    return {
        "strategy": "consensus",
        "prompt": prompt,
        "rounds": records,
        "final": str(final),
        "meta": _meta(coord, start, "consensus"),
    }


STRATEGIES = {
    "broadcast": run_broadcast,
    "sequential": run_sequential,
    "debate": run_debate,
    "supervisor": run_supervisor,
    "consensus": run_consensus,
    "relay": run_relay,
}

# Single source of truth for CLI/MCP choices ("auto" first, then the registry).
STRATEGY_NAMES = ("auto", *STRATEGIES)


def run_strategy(coord, strategy: str, prompt: str, **kwargs) -> Dict[str, Any]:
    """Dispatch to a named strategy (raises ValueError on unknown names)."""
    fn = STRATEGIES.get((strategy or "").lower())
    if fn is None:
        raise ValueError(f"Unknown strategy: {strategy} (available: {sorted(STRATEGIES)})")
    filtered = {k: v for k, v in kwargs.items() if k in inspect.signature(fn).parameters}
    return fn(coord, prompt, **filtered)
