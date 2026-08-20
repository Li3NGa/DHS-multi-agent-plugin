"""上下文压缩策略集成、usage 汇总与 CLI 开关测试（v0.5.0）。"""
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

from deepseek_multi_agent_plugin import (
    Agent,
    AgentCoordinator,
    AgentFactory,
    ContextPolicy,
    DeepseekAdapter,
    build_coordinator,
)
from deepseek_multi_agent_plugin import agents as agents_mod

REPO_ROOT = Path(__file__).resolve().parents[1]


class _FakeResp:
    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def _llm_body():
    return json.dumps({"choices": [{"message": {"content": "ok"}}], "usage": {}}).encode()


def _run_cli(*args):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "deepseek_multi_agent_plugin.cli", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=60,
    )


# ---------------------------------------------------------------- broadcast
def test_broadcast_feed_back_truncated_when_policy_enabled():
    seen = []
    coord = AgentCoordinator(context_policy=ContextPolicy(max_chars=20))
    coord.register_agent(Agent("a", lambda msg: seen.append(str(msg)) or "A-answer"))
    coord.register_agent(Agent("b", lambda msg: seen.append(str(msg)) or "B-answer"))
    result = coord.run("hello", strategy="broadcast", rounds=2)
    # 第二轮输入带 prompt 前缀且被截断（20 字符 + 省略号）
    round2_inputs = [s for s in seen if s.startswith("hello") and len(s) > len("hello")]
    assert round2_inputs
    for inp in round2_inputs:
        assert inp.startswith("hello")
        assert len(inp) <= 21
        assert inp.endswith("…")
    # final 结论永不截断
    assert result["final"] == "A-answer\n\nB-answer"


def test_broadcast_feed_back_unchanged_without_policy():
    seen = []
    coord = AgentCoordinator()
    coord.register_agent(Agent("a", lambda msg: seen.append(str(msg)) or "A1"))
    coord.register_agent(Agent("b", lambda msg: seen.append(str(msg)) or "B1"))
    result = coord.run("hello", strategy="broadcast", rounds=2)
    # 无 policy：第二轮输入就是第一轮汇总（不带 prompt 前缀、不截断）
    assert seen[2] == "A1\n\nB1"
    assert result["final"] == "A1\n\nB1"


# ---------------------------------------------------------------- sequential
def test_sequential_transcript_truncated_prompt_prefix_kept():
    seen = []
    coord = AgentCoordinator(context_policy=ContextPolicy(max_chars=10))
    coord.register_agent(Agent("a", lambda msg: seen.append(str(msg)) or "A-out"))
    coord.register_agent(Agent("b", lambda msg: seen.append(str(msg)) or "B-final"))
    result = coord.run("hello", strategy="sequential")
    assert seen[1].startswith("hello")
    assert len(seen[1]) == 11  # 10 字符 + 省略号
    assert seen[1].endswith("…")
    assert result["final"] == "B-final"  # final 未截断


# ---------------------------------------------------------------- debate
def test_debate_builds_per_agent_context_and_hides_own_statements():
    payloads = []

    def fake_urlopen(req, timeout=None):
        payloads.append(json.loads(req.data))
        return _FakeResp(_llm_body())

    with mock.patch.object(agents_mod.request, "urlopen", fake_urlopen):
        coord = AgentCoordinator(
            context_policy=ContextPolicy(hide_own_statements=True)
        )
        coord.register_agent(AgentFactory.create_agent('deepseek', 'alpha', api_key='k'))
        coord.register_agent(AgentFactory.create_agent('deepseek', 'beta', api_key='k'))
        coord.run("hello", strategy="debate", rounds=2)

    assert len(payloads) == 5  # 两轮 x 两名辩手 + 1 次裁判（默认首位 agent）
    # 辩手并行分发，请求到达顺序不定，不能按下标取 alpha/beta 的请求；
    # 只有第二轮请求带 assistant 历史，按"能看到谁的发言"识别发送者。
    round2 = [
        " ".join(m["content"] for m in p["messages"])
        for p in payloads
        if any(m["role"] == "assistant" for m in p["messages"])
    ]
    assert len(round2) == 2
    sees_beta = [s for s in round2 if "[beta]: ok" in s]
    sees_alpha = [s for s in round2 if "[alpha]: ok" in s]
    # alpha 的请求看得到 beta、看不到自己；beta 的请求反之
    assert len(sees_beta) == 1 and "[alpha]: ok" not in sees_beta[0]
    assert len(sees_alpha) == 1 and "[beta]: ok" not in sees_alpha[0]


def test_debate_judge_input_truncated():
    seen = []
    coord = AgentCoordinator(context_policy=ContextPolicy(max_chars=25))
    coord.register_agent(Agent("a", lambda msg: "A-view"))
    coord.register_agent(Agent("b", lambda msg: "B-view"))
    coord.register_agent(Agent("judge", lambda msg: seen.append(str(msg)) or "VERDICT"))
    result = coord.run("hello", strategy="debate", rounds=1, judge="judge")
    judge_input = seen[0]
    assert judge_input.startswith("hello")
    assert len(judge_input) <= 26
    assert result["final"] == "VERDICT"  # 裁判输出未截断


# ---------------------------------------------------------------- supervisor
def test_supervisor_report_summary_truncated():
    seen = []

    def supervisor_handler(msg):
        seen.append(str(msg))
        return "FINAL-REPORT"

    def worker_handler(msg):
        return "W-" + "x" * 200

    coord = AgentCoordinator(context_policy=ContextPolicy(max_chars=30))
    coord.register_agent(Agent("supervisor", supervisor_handler))
    coord.register_agent(Agent("w1", worker_handler))
    result = coord.run("task", strategy="supervisor")
    report_msg = [m for m in seen if "子任务完成情况" in m][-1]
    assert "…" in report_msg  # 工人结果汇总被截断
    assert result["final"] == "FINAL-REPORT"  # 最终报告未截断


# ---------------------------------------------------------------- consensus
def test_consensus_ballot_truncated():
    votes_seen = []

    def voter(msg):
        text = str(msg)
        if "候选方案" in text:
            votes_seen.append(text)
            return "vote: a"
        return "V-proposal"

    coord = AgentCoordinator(context_policy=ContextPolicy(max_chars=20))
    coord.register_agent(Agent("a", lambda msg: "A-" + "x" * 100))
    coord.register_agent(Agent("b", lambda msg: "B-" + "y" * 100))
    coord.register_agent(Agent("v", voter))
    result = coord.run("pick", strategy="consensus")
    assert "候选方案" in votes_seen[0]
    assert "…" in votes_seen[0]  # ballot 部分被截断
    assert result["final"] == "A-" + "x" * 100  # 胜出方案未截断


# ---------------------------------------------------------------- relay
def test_relay_draft_truncated():
    seen = []

    def make(name, output):
        def handler(msg):
            seen.append(str(msg))
            return output

        return Agent(name, handler)

    coord = AgentCoordinator(context_policy=ContextPolicy(max_chars=30))
    coord.register_agent(make("a", "DRAFT-A"))
    coord.register_agent(make("b", "DRAFT-B"))
    result = coord.run("hello", strategy="relay", rounds=1)
    assert seen[1].startswith("原始任务：hello")
    assert len(seen[1]) <= 31
    assert result["final"] == "DRAFT-B"  # 最终草稿未截断


# ---------------------------------------------------------------- usage meta
def test_meta_usage_zero_filled_when_no_tokens():
    coord = AgentCoordinator()
    coord.register_agent(AgentFactory.create_agent('mock', 'm1'))
    result = coord.run("hi", strategy="broadcast", rounds=1)
    assert result["meta"]["usage"] == {
        "total": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "agents": {},
        "cache_hits": 0,
    }


def test_meta_usage_aggregates_agents_and_cache_hits():
    coord = AgentCoordinator()
    a = AgentFactory.create_agent('mock', 'a')
    a.total_usage = {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}
    b = AgentFactory.create_agent('mock', 'b')
    b.total_usage = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}
    b.cache_hits = 3
    coord.register_agent(a)
    coord.register_agent(b)
    result = coord.run("hi", strategy="broadcast", rounds=1)
    usage = result["meta"]["usage"]
    assert usage["agents"]["a"]["total_tokens"] == 7
    assert usage["agents"]["b"]["total_tokens"] == 12
    assert usage["total"] == {
        "prompt_tokens": 13,
        "completion_tokens": 6,
        "total_tokens": 19,
    }
    assert usage["cache_hits"] == 3


# ---------------------------------------------------------------- coordinator / adapter
def test_build_coordinator_parses_context_and_cache():
    cfg = {
        "coordinator": {
            "context": {"window": 3, "max_chars": 100, "hide_own": True},
            "cache": True,
        },
        "agents": [{"name": "ds", "kind": "deepseek", "api_key": "k"}],
    }
    coord = build_coordinator(cfg)
    assert coord.context_policy.window == 3
    assert coord.context_policy.max_chars == 100
    assert coord.context_policy.hide_own_statements is True
    assert coord.cache is True
    assert coord.get_agent("ds").cache is True


def test_adapter_run_event_passes_context_and_cache():
    coord = AgentCoordinator()
    coord.register_agent(AgentFactory.create_agent('deepseek', 'ds', api_key='k'))
    adapter = DeepseekAdapter(coord)
    with mock.patch.object(
        agents_mod.request, "urlopen", return_value=_FakeResp(_llm_body())
    ) as urlopen:
        adapter.handle_harness_event({
            "type": "run", "prompt": "hi", "strategy": "broadcast", "rounds": 1,
            "context": {"window": 1}, "cache": True,
        })
        adapter.handle_harness_event({
            "type": "run", "prompt": "hi", "strategy": "broadcast", "rounds": 1,
        })
    assert urlopen.call_count == 1  # 第二次命中缓存
    assert coord.context_policy.window == 1
    assert coord.cache is True


def test_coordinator_run_context_override():
    coord = AgentCoordinator()
    coord.register_agent(AgentFactory.create_agent('mock', 'm1'))
    coord.run("hi", strategy="broadcast", rounds=1,
              context=ContextPolicy(window=4, max_chars=99))
    assert coord.context_policy.window == 4
    assert coord.context_policy.max_chars == 99


# ---------------------------------------------------------------- CLI
def test_cli_run_help_lists_context_and_usage_flags():
    proc = _run_cli("run", "--help")
    assert proc.returncode == 0, proc.stderr
    assert "--context-window" in proc.stdout
    assert "--context-max-chars" in proc.stdout
    assert "--cache" in proc.stdout
    assert "--usage" in proc.stdout


def test_cli_demo_json_contains_meta_usage():
    proc = _run_cli(
        "run", "--demo", "--strategy", "broadcast", "--rounds", "1",
        "--prompt", "hello",
        "--context-window", "2", "--context-max-chars", "50",
        "--usage", "--json",
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert set(data["meta"]["usage"]) == {"total", "agents", "cache_hits"}


def test_cli_demo_non_json_usage_after_final():
    proc = _run_cli(
        "run", "--demo", "--strategy", "broadcast", "--rounds", "1",
        "--prompt", "hello", "--usage",
    )
    assert proc.returncode == 0, proc.stderr
    assert "== FINAL ==" in proc.stdout
    assert "== USAGE ==" in proc.stdout
    assert proc.stdout.index("== USAGE ==") > proc.stdout.index("== FINAL ==")
