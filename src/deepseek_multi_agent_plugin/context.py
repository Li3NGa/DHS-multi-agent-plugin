"""上下文压缩与策略级瘦身工具。

本模块提供三样东西：

- ``ContextPolicy``：上下文策略（历史窗口、单条消息长度上限、辩论中隐藏己方旧发言）；
- ``truncate``：通用的前缀截断工具（保留前 N 个字符，末尾追加省略号）；
- ``build_context``：把原始 prompt 与历史消息投影成 OpenAI chat 格式的消息列表，
  同时应用策略（window / max_chars / hide_own_statements）。

所有开关默认关闭；不传策略时行为与旧版本完全一致。
"""
from dataclasses import dataclass
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
        role = msg.get("role")
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
    role = msg.get("role")
    content = str(msg.get("content", ""))
    if role == "assistant" and msg.get("agent"):
        content = f"[{msg['agent']}]: {content}"
    return {"role": role, "content": content}
