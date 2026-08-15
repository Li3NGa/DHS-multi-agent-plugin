"""Tests for the external CLI agent bridge (kind="cli")."""
import sys

import pytest

from deepseek_multi_agent_plugin import AgentCoordinator, AgentFactory


def _agent(code, **kwargs):
    """Build a cli agent that runs ``python -c <code>`` with the message
    appended as the last argument."""
    return AgentFactory.create_agent(
        "cli",
        kwargs.pop("name", "cli_agent"),
        command=sys.executable,
        args=["-c", code],
        **kwargs,
    )


def test_cli_agent_echoes_message():
    agent = _agent("import sys; print('CLI[' + sys.argv[1] + ']')")
    assert agent.handle("hello") == "CLI[hello]"


def test_cli_agent_args_are_passed_before_message():
    code = "import sys; print(sys.argv[2] + ':' + sys.argv[3])"
    agent = AgentFactory.create_agent(
        "cli",
        "cli_args",
        command=sys.executable,
        args=["-c", code, "--prefix", "PRE"],
    )
    assert agent.handle("hello") == "PRE:hello"


def test_cli_agent_nonzero_exit_raises():
    code = "import sys; print('bad thing', file=sys.stderr); sys.exit(3)"
    agent = _agent(code, name="cli_fail")
    with pytest.raises(RuntimeError) as exc:
        agent.handle("hello")
    message = str(exc.value)
    assert "cli_fail" in message
    assert "exited 3" in message
    assert "bad thing" in message


def test_cli_agent_timeout_raises():
    code = "import time; time.sleep(10)"
    agent = _agent(code, name="cli_slow", timeout=0.2)
    with pytest.raises(RuntimeError) as exc:
        agent.handle("hello")
    message = str(exc.value)
    assert any(word in message.lower() for word in ("timeout", "expired", "超时"))
    assert "0.2" in message


def test_cli_agent_missing_command_raises_on_handle():
    agent = AgentFactory.create_agent(
        "cli", "cli_ghost", command="definitely-not-a-real-command-xyz"
    )
    with pytest.raises(RuntimeError) as exc:
        agent.handle("hello")
    message = str(exc.value)
    assert "not found" in message
    assert "definitely-not-a-real-command-xyz" in message


def test_cli_agent_empty_stdout_uses_stderr():
    code = "import sys; print('note', file=sys.stderr)"
    agent = _agent(code)
    assert agent.handle("hello") == "note"


def test_cli_agent_cwd_is_used(tmp_path):
    agent = _agent("import os; print(os.getcwd())", cwd=str(tmp_path))
    assert agent.handle("hello") == str(tmp_path)


def test_cli_agent_from_config_passthrough():
    code = "import sys; print('cfg:' + sys.argv[1])"
    agent = AgentFactory.from_config(
        {
            "name": "codex_worker",
            "kind": "cli",
            "command": sys.executable,
            "args": ["-c", code],
            "timeout": 600,
        }
    )
    assert agent.handle("hi") == "cfg:hi"


def test_cli_agent_in_broadcast_with_mock():
    code = "import sys; print('cli says: ' + sys.argv[1])"
    coord = AgentCoordinator()
    coord.register_agent(
        AgentFactory.create_agent("mock", "mock_agent", message_template="mock says: {msg}")
    )
    coord.register_agent(
        AgentFactory.create_agent(
            "cli", "cli_worker", command=sys.executable, args=["-c", code]
        )
    )
    result = coord.run("hello", strategy="broadcast", rounds=1)
    responses = result["rounds"][0]["responses"]
    assert responses["cli_worker"] == "cli says: hello"
    assert responses["mock_agent"] == "mock says: hello"
