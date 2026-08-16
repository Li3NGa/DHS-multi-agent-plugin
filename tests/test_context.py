"""ContextPolicy / build_context / truncate 单元测试（v0.5.0）。"""
from deepseek_multi_agent_plugin import ContextPolicy, build_context, truncate


# ---------------------------------------------------------------- truncate
def test_truncate_none_returns_as_is():
    assert truncate("hello", None) == "hello"
    assert truncate(123, None) == "123"


def test_truncate_short_text_unchanged():
    assert truncate("abc", 5) == "abc"


def test_truncate_long_text_keeps_prefix_and_ellipsis():
    assert truncate("abcdefghij", 5) == "abcde…"


def test_truncate_zero_chars():
    assert truncate("abc", 0) == "…"


# ---------------------------------------------------------------- policy
def test_policy_from_dict():
    policy = ContextPolicy.from_dict({"window": 6, "max_chars": 100, "hide_own": True})
    assert policy.window == 6
    assert policy.max_chars == 100
    assert policy.hide_own_statements is True


def test_policy_from_dict_accepts_full_field_name():
    policy = ContextPolicy.from_dict({"hide_own_statements": True})
    assert policy.hide_own_statements is True


def test_policy_from_dict_empty_returns_none():
    assert ContextPolicy.from_dict(None) is None
    assert ContextPolicy.from_dict({}) is None


def test_policy_defaults_all_off():
    policy = ContextPolicy()
    assert policy.window is None
    assert policy.max_chars is None
    assert policy.hide_own_statements is False


# ---------------------------------------------------------------- build_context
def test_build_context_keeps_prompt_first_and_never_truncates():
    messages = [{"role": "assistant", "content": "x" * 500, "agent": "a"}]
    out = build_context("PROMPT", messages, ContextPolicy(max_chars=50))
    assert out[0] == {"role": "user", "content": "PROMPT"}
    # 截断作用于原始内容，说话人前缀不计入 max_chars
    assert out[1]["content"] == "[a]: " + "x" * 50 + "…"


def test_build_context_window_keeps_recent_history():
    messages = [
        {"role": "assistant", "content": f"m{i}", "agent": f"a{i}"}
        for i in range(5)
    ]
    out = build_context("p", messages, ContextPolicy(window=2))
    assert [m["content"] for m in out[1:]] == ["[a3]: m3", "[a4]: m4"]


def test_build_context_window_zero_keeps_only_prompt():
    messages = [{"role": "assistant", "content": "m", "agent": "a"}]
    out = build_context("p", messages, ContextPolicy(window=0))
    assert out == [{"role": "user", "content": "p"}]


def test_build_context_hide_own_statements():
    messages = [
        {"role": "user", "content": "prompt"},
        {"role": "assistant", "content": "alpha says", "agent": "alpha"},
        {"role": "assistant", "content": "beta says", "agent": "beta"},
    ]
    out = build_context(
        "prompt",
        messages,
        ContextPolicy(hide_own_statements=True),
        agent_name="alpha",
    )
    contents = [m["content"] for m in out]
    assert "alpha says" not in contents
    assert "[beta]: beta says" in contents


def test_build_context_hide_own_ignored_without_agent_name():
    messages = [{"role": "assistant", "content": "alpha says", "agent": "alpha"}]
    out = build_context("prompt", messages, ContextPolicy(hide_own_statements=True))
    assert len(out) == 2


def test_build_context_dedupes_leading_prompt():
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "a", "agent": "alpha"},
    ]
    out = build_context("hi", messages, ContextPolicy())
    assert len(out) == 2
    assert out[0] == {"role": "user", "content": "hi"}
    assert out[1]["role"] == "assistant"


def test_build_context_no_policy_passthrough():
    messages = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "a", "agent": "x"},
    ]
    out = build_context("q", messages, None)
    assert len(out) == 2
    assert out[1] == {"role": "assistant", "content": "[x]: a"}
