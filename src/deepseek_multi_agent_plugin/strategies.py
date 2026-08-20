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

from .context import build_context, truncate
from .exceptions import AgentNotFound, StrategyError
from .observability import Span, current_trace, note_agent_call


def _policy(coord):
    """读取协调器上的上下文策略（未配置时为 None）。"""
    return getattr(coord, "context_policy", None)


def _max_chars(coord) -> Optional[int]:
    """读取策略中的逐条截断上限（未配置时为 None）。"""
    policy = _policy(coord)
    return policy.max_chars if policy is not None else None


def _call_agent(agent, message, context=None, timeout=None, trace=None):
    """Call one agent; exceptions are returned as {"error": ...} dicts.

    On timeout the executor is shut down without waiting, so a hung agent
    never blocks the strategy thread past its timeout (the worker thread
    itself keeps running until the agent's own HTTP timeout fires).

    每次调用都会记录 span 与 agent 健康计数；``trace`` 由并行执行器显式
    传入（执行器线程看不到发起线程的 contextvar），串行路径自动取当前
    trace，没有 trace 时零开销。
    """
    active = trace if trace is not None else current_trace()
    start = time.perf_counter()
    result = None
    try:
        if timeout is None:
            try:
                result = agent.handle(message, context)
            except Exception as e:  # noqa: BLE001 - strategy-level resilience
                result = {"error": str(e)}
        else:
            ex = ThreadPoolExecutor(max_workers=1)
            try:
                fut = ex.submit(agent.handle, message, context)
                result = fut.result(timeout=timeout)
            except (TimeoutError, FuturesTimeoutError):
                result = {"error": "timeout"}
            except Exception as e:  # noqa: BLE001 - strategy-level resilience
                result = {"error": str(e)}
            finally:
                ex.shutdown(wait=False, cancel_futures=True)
        return result
    finally:
        elapsed = (time.perf_counter() - start) * 1000.0
        error = result.get("error") if isinstance(result, dict) else None
        status = "timeout" if error == "timeout" else ("error" if error else "ok")
        note_agent_call(agent, status, elapsed / 1000.0)
        if active is not None:
            active.add_span(Span(agent=getattr(agent, "name", "?"), status=status,
                                 duration_ms=elapsed, error=error))


def _parallel(
    coord,
    message,
    agents=None,
    context=None,
    contexts=None,
    timeout=None,
) -> Dict[str, Any]:
    """Ask every agent in parallel; errors are captured per agent.

    ``context`` is shared by every agent; ``contexts`` is an optional
    ``{agent_name: chat_messages}`` mapping that overrides the shared context
    per agent (used by debate to give each debater a customized view).
    """
    targets = agents if agents is not None else coord.agents
    results: Dict[str, Any] = {}
    # 执行器线程看不到发起线程的 contextvar，这里显式捕获并逐个传入。
    trace = current_trace()
    ex = ThreadPoolExecutor(max_workers=max(1, len(targets)))
    futures = {
        ex.submit(
            _call_agent,
            a,
            message,
            contexts.get(a.name, context) if contexts is not None else context,
            timeout,
            trace,
        ): a.name
        for a in targets
    }
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
    """构建运行元信息；usage 升级为 {total, agents, cache_hits} 汇总形状。"""
    agents_usage: Dict[str, Dict[str, int]] = {}
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    cache_hits = 0
    for a in coord.agents:
        usage = getattr(a, "total_usage", {}) or {}
        if usage.get("total_tokens"):
            agents_usage[a.name] = dict(usage)
            for key in totals:
                totals[key] += usage.get(key, 0) or 0
        cache_hits += int(getattr(a, "cache_hits", 0) or 0)
    meta: Dict[str, Any] = {
        "elapsed_seconds": round(time.time() - start, 3),
        "agents": [a.name for a in coord.agents],
        "strategy": strategy,
        # v0.5.0：usage 恒存在（零值填充），JSON 输出总能拿到计量摘要
        "usage": {
            "total": totals,
            "agents": agents_usage,
            "cache_hits": cache_hits,
        },
    }
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
    max_chars = _max_chars(coord)
    total_rounds = max(1, int(rounds))
    _record(coord, "user", prompt)
    for r in range(1, total_rounds + 1):
        responses = _parallel(coord, last, timeout=timeout)
        for name, resp in responses.items():
            if not _is_error(resp):
                _record(coord, "assistant", resp, agent=name)
        records.append({"round": r, "kind": "broadcast", "responses": responses})
        joined = _join(responses, fallback=last)
        if max_chars is not None and r < total_rounds:
            # 回喂消息按 max_chars 截断（prompt 前缀保留）；final 结论永不截断
            last = truncate(f"{prompt}\n\n{joined}", max_chars)
        else:
            last = joined
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
        raise AgentNotFound(f"sequential: unknown agents in order: {missing}")
    records = []
    transcript = str(prompt)
    max_chars = _max_chars(coord)
    _record(coord, "user", prompt)
    for i, name in enumerate(names, 1):
        resp = _call_agent(coord.get_agent(name), transcript, timeout=timeout)
        if not _is_error(resp):
            _record(coord, "assistant", resp, agent=name)
        records.append({"step": i, "agent": name, "response": resp})
        next_transcript = f"{transcript}\n\n[{name}]: {resp}"
        # 传给下一棒的 transcript 按 max_chars 截断（prompt 前缀保留）
        transcript = truncate(next_transcript, max_chars) if max_chars is not None else next_transcript
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
        raise StrategyError("debate needs at least two agents")
    policy = _policy(coord)
    max_chars = _max_chars(coord)
    _record(coord, "user", prompt)
    last_responses = {}
    for r in range(1, max(1, int(rounds)) + 1):
        if policy is not None:
            # 按策略为每位辩手生成定制 context（窗口/截断/隐藏己方旧发言）
            history = coord.memory.all()
            contexts = {
                name: build_context(prompt, history, policy, agent_name=name)
                for name in names
            }
            responses = _parallel(coord, prompt, contexts=contexts, timeout=timeout)
        else:
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
        raise AgentNotFound(f"debate: judge agent '{judge_name}' not registered")
    judge_input = (
        f"{prompt}\n\n以下是各位辩手的观点:\n{_format_statements(last_responses)}\n\n"
        "请以裁判身份综合所有观点，给出最终结论与理由。"
    )
    if max_chars is not None:
        # 裁判输入按 max_chars 截断（prompt 前缀保留）；裁判输出永不截断
        judge_input = truncate(judge_input, max_chars)
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
        raise AgentNotFound(f"supervisor: agent '{sup_name}' not registered")
    worker_names = list(workers) if workers else [n for n in names if n != sup_name]
    if not worker_names:
        raise StrategyError("supervisor strategy needs at least one worker besides the supervisor")
    missing = [n for n in worker_names if coord.get_agent(n) is None]
    if missing:
        raise AgentNotFound(f"supervisor: unknown worker agents: {missing}")

    records = []
    _record(coord, "user", prompt)
    max_chars = _max_chars(coord)

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
    work_trace = current_trace()
    ex = ThreadPoolExecutor(max_workers=max(1, len(assigned)))
    futures = {
        ex.submit(_call_agent, coord.get_agent(w), "\n".join(tasks), None, timeout, work_trace): w
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
    summary = _format_statements(results)
    if max_chars is not None:
        # 工人结果汇总按 max_chars 截断；最终报告本身永不截断
        summary = truncate(summary, max_chars)
    report = _call_agent(
        sup,
        f"{prompt}\n\n子任务完成情况:\n{summary}\n\n请综合所有子任务结果，给出最终的完整回答。",
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
        raise StrategyError("relay needs at least two agents")
    missing = [n for n in names if coord.get_agent(n) is None]
    if missing:
        raise AgentNotFound(f"relay: unknown agents in order: {missing}")
    records = []
    draft = str(prompt)
    max_chars = _max_chars(coord)
    _record(coord, "user", prompt)
    for r in range(1, max(1, int(rounds)) + 1):
        round_start = draft
        steps = []
        for i, name in enumerate(names, 1):
            message = (
                f"原始任务：{prompt}\n\n当前草稿：\n{draft}\n\n"
                "要求：请改进下面这份草稿，只输出改进后的完整草稿。"
            )
            if max_chars is not None:
                # 传给下一棒的草稿按 max_chars 截断（prompt 前缀保留）；最终草稿永不截断
                message = truncate(message, max_chars)
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
        raise StrategyError("consensus needs at least two agents")
    records = []
    max_chars = _max_chars(coord)
    _record(coord, "user", prompt)

    proposals = _parallel(coord, prompt, timeout=timeout)
    for name, resp in proposals.items():
        if not _is_error(resp):
            _record(coord, "assistant", resp, agent=name)
    records.append({"step": "propose", "responses": proposals})

    ballot = _format_statements(proposals)
    if max_chars is not None:
        # 投票候选 ballot 按 max_chars 截断（prompt 前缀保留）；最终胜出方案永不截断
        ballot = truncate(ballot, max_chars)
    vote_prompt = f"{prompt}\n\n候选方案:\n{ballot}\n\n请投票选出最佳方案，输出格式: vote:<agent_name>"
    votes = _parallel(coord, vote_prompt, timeout=timeout)
    records.append({"step": "vote", "votes": votes})

    counts: Counter = Counter()
    for vote_text in votes.values():
        w = _parse_vote(vote_text, names)
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
        raise StrategyError(f"Unknown strategy: {strategy} (available: {sorted(STRATEGIES)})")
    filtered = {k: v for k, v in kwargs.items() if k in inspect.signature(fn).parameters}
    return fn(coord, prompt, **filtered)
