# -*- coding: utf-8 -*-
"""Task / Trace / Agent 可观测性。

- :class:`Trace`：每次 ``coordinator.run`` 生成一个，持有稳定的 ``run_id``、
  spans（每次 agent 调用的耗时 / 状态）与 tasks（策略步骤记录）。
- :class:`RunRegistry`：有界的进程内运行历史（默认 100 条），供 HTTP / MCP
  查询最近的运行（``GET /runs``、``GET /runs/{run_id}``）。
- Agent 健康计数器：懒挂载到 agent 实例上（calls / ok / error / timeout /
  累计耗时），由 ``note_agent_call`` 维护，通过 :func:`agent_health` 读取。

追踪是被动的：没有活动 trace 时，span 记录只是一次字典查找，策略代码零开销。
线程模型：trace 在发起 run 的线程中创建；并行策略把 trace 显式传给执行器
线程（见 strategies._parallel / run_supervisor），因此并发 run 不会串扰。
"""
import threading
import time
import uuid
from collections import deque
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

_current_trace: ContextVar[Optional["Trace"]] = ContextVar("dsma_current_trace", default=None)


def current_trace() -> Optional["Trace"]:
    """当前线程活动中的 trace（无则 None）。"""
    return _current_trace.get()


def activate_trace(trace: Optional["Trace"]) -> Any:
    """把 trace 设为当前线程的活动 trace，返回用于 restore 的 token。"""
    return _current_trace.set(trace)


def restore_trace(token: Any) -> None:
    """恢复 activate_trace 之前的 trace 状态。"""
    _current_trace.reset(token)


class Span:
    """一次被观测到的 agent 调用。"""

    __slots__ = ("agent", "kind", "status", "duration_ms", "error", "at")

    def __init__(self, agent: str, status: str, duration_ms: float,
                 kind: str = "agent", error: Optional[str] = None):
        self.agent = agent
        self.kind = kind
        self.status = status  # ok | error | timeout
        self.duration_ms = round(float(duration_ms), 1)
        self.error = error
        self.at = datetime.now().isoformat(timespec="milliseconds")

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "agent": self.agent,
            "kind": self.kind,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "at": self.at,
        }
        if self.error is not None:
            out["error"] = self.error
        return out


class Task:
    """一个策略步骤（round / judge / plan / work / report / propose / vote）。"""

    __slots__ = ("name", "kind", "status", "agent")

    def __init__(self, name: str, kind: str, status: str = "ok", agent: Optional[str] = None):
        self.name = name
        self.kind = kind
        self.status = status
        self.agent = agent

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"name": self.name, "kind": self.kind, "status": self.status}
        if self.agent is not None:
            out["agent"] = self.agent
        return out


def _step_status(record: Dict[str, Any]) -> str:
    """从一条 rounds 记录推断步骤状态：任何子结果是 error/timeout 即 error。"""
    for key in ("responses", "results", "votes"):
        value = record.get(key)
        if isinstance(value, dict):
            for item in value.values():
                if isinstance(item, dict) and "error" in item:
                    return "error"
    response = record.get("response")
    if isinstance(response, dict) and "error" in response:
        return "error"
    return "ok"


class Trace:
    """一次协作运行的完整观测记录。"""

    def __init__(self, prompt: str, strategy: str):
        self.run_id = uuid.uuid4().hex[:12]
        self.prompt = str(prompt)[:200]
        self.strategy = strategy
        self.started_at = datetime.now().isoformat(timespec="milliseconds")
        self.finished_at: Optional[str] = None
        self.status = "running"
        self.error: Optional[str] = None
        self.spans: List[Span] = []
        self.tasks: List[Task] = []
        self._lock = threading.Lock()
        self.recorded = False

    def add_span(self, span: Span) -> None:
        with self._lock:
            self.spans.append(span)

    def add_task(self, task: Task) -> None:
        with self._lock:
            self.tasks.append(task)

    def tasks_from_rounds(self, records: List[Any]) -> None:
        """由策略结果中的 rounds 记录派生 task 列表（不改动策略代码）。"""
        for record in records:
            if not isinstance(record, dict):
                continue
            kind = record.get("kind") or str(record.get("step") or "round")
            if "round" in record:
                name = f"round {record['round']}"
            else:
                name = str(record.get("step") or kind)
            self.add_task(Task(name=name, kind=str(kind),
                               status=_step_status(record),
                               agent=record.get("agent")))

    def finish(self, error: Optional[str] = None) -> None:
        with self._lock:
            if self.finished_at is not None:
                return
            self.finished_at = datetime.now().isoformat(timespec="milliseconds")
            self.error = error
            self.status = "error" if error else "ok"

    def _summary_locked(self) -> Dict[str, Any]:
        spans = self.spans
        ok = sum(1 for s in spans if s.status == "ok")
        return {
            "run_id": self.run_id,
            "strategy": self.strategy,
            "status": self.status,
            "prompt": self.prompt,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "spans": len(spans),
            "span_errors": len(spans) - ok,
            "tasks": len(self.tasks),
            "error": self.error,
        }

    def summary(self) -> Dict[str, Any]:
        """轻量摘要（列表查询用）。"""
        with self._lock:
            return self._summary_locked()

    def to_dict(self) -> Dict[str, Any]:
        """完整明细（单次查询用）。"""
        with self._lock:
            out = self._summary_locked()
            out["span_list"] = [s.as_dict() for s in self.spans]
            out["task_list"] = [t.as_dict() for t in self.tasks]
            return out


class RunRegistry:
    """有界的进程内运行注册表（线程安全）。"""

    def __init__(self, limit: int = 100):
        self._runs: Deque[Trace] = deque(maxlen=max(1, int(limit)))
        self._index: Dict[str, Trace] = {}
        self._lock = threading.Lock()

    def record(self, trace: Trace) -> None:
        with self._lock:
            if trace.recorded:
                return
            trace.recorded = True
            self._runs.append(trace)
            self._index[trace.run_id] = trace
            if len(self._index) > self._runs.maxlen:
                # deque 已淘汰最老条目，同步收缩索引
                alive = {t.run_id for t in self._runs}
                for key in list(self._index):
                    if key not in alive:
                        del self._index[key]

    def get(self, run_id: str) -> Optional[Trace]:
        with self._lock:
            return self._index.get(run_id)

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        """最近 limit 次运行的摘要（最新在前）。"""
        with self._lock:
            limit = max(0, int(limit))
            if limit == 0:
                return []
            traces = list(self._runs)[-limit:]
        return [t.summary() for t in reversed(traces)]

    def __len__(self) -> int:
        with self._lock:
            return len(self._runs)


class AgentHealth:
    """单个 agent 的健康计数器（线程安全）。"""

    def __init__(self):
        self.calls = 0
        self.ok = 0
        self.errors = 0
        self.timeouts = 0
        self.total_ms = 0.0
        self._lock = threading.Lock()

    def note(self, status: str, seconds: float) -> None:
        with self._lock:
            self.calls += 1
            self.total_ms += seconds * 1000.0
            if status == "ok":
                self.ok += 1
            elif status == "timeout":
                self.timeouts += 1
            else:
                self.errors += 1

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            avg = round(self.total_ms / self.calls, 1) if self.calls else 0.0
            return {
                "calls": self.calls,
                "ok": self.ok,
                "errors": self.errors,
                "timeouts": self.timeouts,
                "avg_ms": avg,
            }


def _health_of(agent: Any) -> AgentHealth:
    health = getattr(agent, "_dsma_health", None)
    if health is None:
        health = AgentHealth()
        try:
            agent._dsma_health = health
        except (AttributeError, TypeError):
            pass
    return health


def note_agent_call(agent: Any, status: str, seconds: float) -> None:
    """记录一次 agent 调用的结果（无健康对象时静默跳过）。"""
    _health_of(agent).note(status, seconds)


def agent_health(agent: Any) -> Dict[str, Any]:
    """读取 agent 的健康计数快照。"""
    return _health_of(agent).snapshot()


def span_started() -> float:
    return time.perf_counter()
