"""Smoke test: exercise the installed package end to end without pytest.

Used by CI after building/installing the wheel:

  python scripts/smoke_test.py

Checks: import + version, CLI run (mock team, all strategies), CLI --version,
token/trace flags, and the MCP stdio handshake.
"""
import json
import subprocess
import sys


def ok(label):
    print(f"  ok: {label}")


def main() -> int:
    print("== smoke: import ==")
    import deepseek_multi_agent_plugin as pkg
    assert pkg.__version__ and len(pkg.__version__.split(".")) == 3
    ok(f"version {pkg.__version__}")

    print("== smoke: cli --version ==")
    out = subprocess.run([sys.executable, "-m", "deepseek_multi_agent_plugin.cli", "--version"],
                         capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0 and pkg.__version__ in out.stdout, out.stderr
    ok("cli --version")

    print("== smoke: cli strategies ==")
    for strategy in ("broadcast", "sequential", "debate", "consensus", "relay"):
        out = subprocess.run(
            [sys.executable, "-m", "deepseek_multi_agent_plugin.cli", "run", "--demo",
             "--strategy", strategy, "--prompt", "smoke", "--rounds", "1",
             "--usage", "--trace"],
            capture_output=True, text=True, encoding="utf-8", timeout=120)
        assert out.returncode == 0, f"{strategy}: {out.stderr}"
        assert "== FINAL ==" in out.stdout
        assert '"run_id"' in out.stdout
        ok(f"cli run {strategy}")

    print("== smoke: mcp handshake ==")
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "smoke", "version": "0"}}}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
    ]
    out = subprocess.run(
        [sys.executable, "-m", "deepseek_multi_agent_plugin.mcp_server", "--demo"],
        input="\n".join(lines) + "\n", capture_output=True, text=True,
        encoding="utf-8", timeout=120)
    assert out.returncode == 0, out.stderr
    msgs = [json.loads(line) for line in out.stdout.strip().splitlines()]
    assert {t["name"] for t in msgs[1]["result"]["tools"]} >= {
        "run", "agents", "register", "status", "history", "runs"}
    ok("mcp initialize + tools/list")

    print("== smoke: PASSED ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
