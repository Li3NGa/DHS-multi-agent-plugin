# -*- coding: utf-8 -*-
"""CLI 端到端测试：用 subprocess 调用 `python -m deepseek_multi_agent_plugin.cli`。"""
import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args, timeout: float = 60.0):
    """在仓库根目录用当前解释器调用 CLI 模块，输出统一按 UTF-8 解码。"""
    env = dict(os.environ)
    # 子进程管道输出固定为 UTF-8，避免 Windows 默认代码页影响中文内容解析
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "deepseek_multi_agent_plugin.cli", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=timeout,
    )


def test_run_demo_broadcast_json():
    proc = _run_cli(
        "run", "--demo", "--strategy", "broadcast",
        "--rounds", "1", "--prompt", "hello", "--json",
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    # strategy 字段应为实际选中的 broadcast（非默认 auto），final 非空
    assert data["strategy"] == "broadcast"
    assert data["strategy"] != "auto"
    assert data["final"]


def test_run_demo_relay_json():
    # 注：run 子命令的 --prompt 是必填项，任务书 b) 里省略了它，此处补上
    proc = _run_cli(
        "run", "--demo", "--strategy", "relay",
        "--rounds", "1", "--prompt", "hello", "--json",
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["strategy"] == "relay"


def test_agents_demo_prints_two_json_lines():
    proc = _run_cli("agents", "--demo")
    assert proc.returncode == 0, proc.stderr
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert len(lines) == 2
    agents = [json.loads(line) for line in lines]
    assert {agent["name"] for agent in agents} == {"alpha", "beta"}


def test_agents_demo_json_array():
    proc = _run_cli("agents", "--demo", "--json")
    assert proc.returncode == 0, proc.stderr
    agents = json.loads(proc.stdout)
    assert isinstance(agents, list)
    assert {agent["name"] for agent in agents} == {"alpha", "beta"}


def test_run_help_lists_workers():
    proc = _run_cli("run", "--help")
    assert proc.returncode == 0, proc.stderr
    assert "--workers" in proc.stdout


def test_serve_help_lists_history_options():
    proc = _run_cli("serve", "--help")
    assert proc.returncode == 0, proc.stderr
    assert "--history" in proc.stdout
    assert "--history-prompt-limit" in proc.stdout


def test_run_unknown_strategy_fails_with_hint():
    proc = _run_cli(
        "run", "--demo", "--strategy", "bogus",
        "--rounds", "1", "--prompt", "hello", "--json",
    )
    assert proc.returncode != 0
    # argparse 的 choices 校验会在 stderr 给出含 --strategy 的提示
    assert "strategy" in proc.stderr.lower()
