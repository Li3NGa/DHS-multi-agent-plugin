"""上下文压缩与策略级瘦身工具。

本模块提供三样东西：

- ``ContextPolicy``：上下文策略（历史窗口、单条消息长度上限、辩论中隐藏己方旧发言）；
- ``truncate``：通用的前缀截断工具（保留前 N 个字符，末尾追加省略号）；
- ``build_context``：把原始 prompt 与历史消息投影成 OpenAI chat 格式的消息列表，
  同时应用策略（window / max_chars / hide_own_statements）。

所有开关默认关闭；不传策略时行为与旧版本完全一致。

另外，本模块也定义了运行时协作取消的核心类型：

- ``CancellationToken``：一个可共享、可轮询的取消令牌。它**只**表达“请求取消”，
  绝不杀死任何线程。正在运行的任务必须主动检查它并自行退出（协作式取消）。
- ``TaskContext``：传递给每个 Task 的运行时上下文，至少包含：

  - ``task_id``：任务标识；
  - ``cancellation``：该任务可见的 ``CancellationToken``；
  - ``deadline``：该任务的截止时刻（monotonic 秒），到期即视为超时。

  ``TaskContext`` 在命名空间上对应单个 Task；运行级（Run）的截止时刻通过
  ``runtime.deadline`` 的上下文变量传播，二者职责分离：

  - **task deadline** ＝ 单任务最长执行时间（``Task.timeout``）；
  - **run deadline** ＝ 整次运行（一次 ``scheduler.execute`` 调用）的截止时刻；
  - **provider timeout** ＝ 单次 LLM/HTTP 调用的超时（由 ``clamp_timeout`` 处理）。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

ELLIPSIS = "…"


@dataclass
class ContextPolicy:
    """上下文压缩策略（全部可选，默认不压缩）。

    window:
        历史窗口：只保留最近 N 条历史消息（原始 prompt 不受窗口限制，永远保留）。
    max_chars:
        逐条截断：每条消息内容保留前 max_chars 个字符并追加省略号 "…"。
    hide_own_statements:
        辩论场景中，辩手看不到自己之前的 assistant 发言（需要同时传入 agent_name）。
    """

    window: Optional[int] = None
    max_chars: Optional[int] = None
    hide_own_statements: bool = False

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["ContextPolicy"]:
        """从配置 dict 构建策略；空配置返回 None（默认关闭）。

        支持 ``window`` / ``max_chars`` / ``hide_own`` 三个键（示例配置使用
        ``hide_own`` 简写，也接受 ``hide_own_statements`` 全名）。
        """
        if not data:
            return None
        window = data.get("window")
        max_chars = data.get("max_chars")
        hide_own = data.get("hide_own", data.get("hide_own_statements", False))
        return cls(
            window=int(window) if window is not None else None,
            max_chars=int(max_chars) if max_chars is not None else None,
            hide_own_statements=bool(hide_own),
        )


def truncate(text: Any, max_chars: Optional[int]) -> str:
    """保留前 ``max_chars`` 个字符并追加省略号；``max_chars`` 为 None 时原样返回。"""
    if max_chars is None:
        return str(text)
    text = str(text)
    limit = max(0, int(max_chars))
    if len(text) <= limit:
        return text
    return text[:limit] + ELLIPSIS


def build_context(
    prompt: str,
    messages: List[Dict[str, Any]],
    policy: Optional[ContextPolicy],
    agent_name: Optional[str] = None,
) -> List[Dict[str, str]]:
    """把 prompt 与历史消息投影成 OpenAI chat 格式。

    规则：

    - 原始 prompt（role=user）永远放在首位，绝不截断、绝不被窗口丢弃；
    - 若历史首条恰好是同一个 prompt，则去重（避免 LLM 请求里出现重复提问）；
    - ``window`` 只作用于历史消息（保留最近 N 条）；
    - ``max_chars`` 对每条历史消息单独截断；
    - ``hide_own_statements=True`` 且给出 ``agent_name`` 时，过滤该 agent
      自己之前的 assistant 发言（通过消息的 ``agent`` 字段识别）；
    - 带 ``agent`` 字段的 assistant 消息会加上 ``[agent名]: `` 说话人前缀，
      与 ``MessageStore.to_chat(with_speaker=True)`` 的既有行为一致。
    """
    out: List[Dict[str, str]] = [{"role": "user", "content": str(prompt)}]
    history = [
        dict(m) for m in (messages or [])
        if m.get("role") in ("user", "assistant", "system")
    ]
    # 去重：历史首条若与原始 prompt 相同，不再重复放入
    if (
        history
        and history[0].get("role") == "user"
        and str(history[0].get("content", "")) == str(prompt)
    ):
        history = history[1:]

    if policy is None:
        for msg in history:
            out.append(_project_message(msg))
        return out

    if policy.window is not None:
        window = max(0, int(policy.window))
        history = history[-window:] if window > 0 else []

    for msg in history:
        role = msg.get("role") or ""
        if (
            policy.hide_own_statements
            and agent_name is not None
            and role == "assistant"
            and msg.get("agent") == agent_name
        ):
            continue
        content = str(msg.get("content", ""))
        if policy.max_chars is not None:
            content = truncate(content, policy.max_chars)
        if role == "assistant" and msg.get("agent"):
            content = f"[{msg['agent']}]: {content}"
        out.append({"role": role, "content": content})
    return out


def _project_message(msg: Dict[str, Any]) -> Dict[str, str]:
    """把一条内存消息投影成 chat 消息（无策略时也只做说话人前缀处理）。"""
    role = msg.get("role") or ""
    content = str(msg.get("content", ""))
    if role == "assistant" and msg.get("agent"):
        content = f"[{msg['agent']}]: {content}"
    return {"role": role, "content": content}


# ----------------------------------------------------------------------
# 协作式取消（cooperative cancellation）
# ----------------------------------------------------------------------
class CancelledError(BaseException):
    """协作式取消信号。

    继承 ``BaseException`` 而非 ``Exception``，确保它不会被任务体里普通的
    ``except Exception`` 吞掉；同时它也不是 ``KeyboardInterrupt`` 的子类，
    避免与进程级信号混淆。
    """

    def __init__(self, reason: str = "cancelled") -> None:
        super().__init__(reason)
        self.reason = reason


class CancellationToken:
    """一个可共享、可轮询的取消令牌。

    重要语义（修复前的 P0 缺陷）：

    - 它**只**表达“请求取消”，**绝不**杀死任何线程或 future。
    - ``future.cancel()`` 只能取消**尚未开始**的 future；已经开始运行的
      Python 线程无法被强制终止。因此运行中的任务必须**主动**调用
      :meth:`is_cancelled` / :meth:`raise_if_cancelled` 检查本令牌，并自行退出。
    - 调用方在超时/失败时调用 :meth:`cancel` 仅用于“发出请求”，真正的停止
      依赖任务内部的协作检查（再叠加 provider timeout / HTTP timeout 让阻塞
      的 I/O 最终返回）。

    令牌支持父子链（``parent=``）：run 级令牌是所有 task 令牌的父节点，
    父令牌取消后所有子令牌的 :meth:`is_cancelled` 立即返回 True（运行截止
    传播给每个运行中的任务）；反向不成立——取消单个任务令牌不影响兄弟任务
    也不影响父令牌。
    """

    __slots__ = ("_cancelled", "_reason", "_lock", "_parent")

    def __init__(self, parent: Optional["CancellationToken"] = None) -> None:
        self._parent = parent
        self._cancelled = False
        self._reason: Optional[str] = None
        self._lock = threading.Lock()

    def cancel(self, reason: Optional[str] = None) -> None:
        """请求取消。幂等；可重复调用，``reason`` 仅保留首次非空值。"""
        with self._lock:
            if not self._cancelled:
                self._cancelled = True
                self._reason = reason

    def is_cancelled(self) -> bool:
        """本令牌或其任何祖先令牌已被请求取消时返回 ``True``。"""
        token: Optional["CancellationToken"] = self
        while token is not None:
            if token._cancelled:
                return True
            token = token._parent
        return False

    def reason(self) -> Optional[str]:
        """首个被置位的取消原因（先查本令牌，再沿父链向上）。"""
        token: Optional["CancellationToken"] = self
        while token is not None:
            if token._cancelled:
                return token._reason
            token = token._parent
        return None

    def raise_if_cancelled(self, default_reason: str = "cancelled") -> None:
        """若已请求取消则抛出 ``CancelledError``，否则什么都不做。

        任务体可在安全检查点周期性调用本方法以实现协作式退出。
        """
        if self.is_cancelled():
            raise CancelledError(self.reason() or default_reason)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"CancellationToken(cancelled={self.is_cancelled()!r})"


@dataclass
class TaskContext:
    """传递给单个 Task 的运行时上下文。

    含义分层（对应题目要求的三种超时/截止区分）：

    - ``task_id``：任务标识，用于在上下文中定位本次执行。
    - ``cancellation``：该任务可见的 :class:`CancellationToken`。运行级取消
      会让所有 Task 的令牌进入 cancelled 状态，从而请求它们停止。
    - ``deadline``：该任务的**截止时刻**（``time.monotonic()`` 秒）。由调度器
      根据 ``Task.timeout`` 与剩余 run 预算计算得到；任务内部可用它来
      ``clamp_timeout``，判断自身是否超时。

    Run 级别的截止时刻（run deadline）不放在这里，而是通过
    ``runtime.deadline.run_deadline()`` 上下文变量传播，二者各司其职。
    """

    task_id: str
    cancellation: CancellationToken
    deadline: Optional[float] = None
    # 可选：任务可见的额外运行参数（保持扩展性，不改变既有 API）
    meta: Dict[str, Any] = field(default_factory=dict)

    def remaining(self) -> Optional[float]:
        """返回到 task deadline 的剩余秒数；无 deadline 时返回 ``None``。"""
        if self.deadline is None:
            return None
        return max(0.0, self.deadline - time.monotonic())

    def is_expired(self) -> bool:
        """task deadline 是否已过。"""
        return self.deadline is not None and self.deadline <= time.monotonic()
