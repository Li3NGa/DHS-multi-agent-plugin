"""Tests for config loading and coordinator construction."""
import pytest

from deepseek_multi_agent_plugin import build_coordinator, load_config


def test_build_coordinator_from_dict():
    cfg = {
        "coordinator": {"timeout_seconds": 5},
        "agents": [
            {"name": "a1", "kind": "mock", "message_template": "x {msg}"},
            {"name": "a2", "kind": "echo"},
        ],
    }
    coord = build_coordinator(cfg)
    assert coord.agent_names == ["a1", "a2"]
    assert coord.timeout == 5.0
    assert coord.get_agent("a2").handle("hi") == "a2 echo: hi"


def test_build_coordinator_empty():
    coord = build_coordinator({})
    assert coord.agent_names == []


def test_load_config_yaml(tmp_path):
    pytest.importorskip("yaml")
    p = tmp_path / "cfg.yaml"
    p.write_text(
        "coordinator:\n  rounds: 2\nagents:\n  - name: a\n    kind: mock\n",
        encoding="utf-8",
    )
    cfg = load_config(str(p))
    assert cfg["coordinator"]["rounds"] == 2
    assert cfg["agents"][0]["name"] == "a"


def test_load_config_json(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text('{"agents": [{"name": "a", "kind": "echo"}]}', encoding="utf-8")
    cfg = load_config(str(p))
    assert cfg["agents"][0]["name"] == "a"


def test_load_config_bad_extension(tmp_path):
    p = tmp_path / "cfg.txt"
    p.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(str(p))


def test_config_path_build(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text('{"agents": [{"name": "a", "kind": "echo"}]}', encoding="utf-8")
    coord = build_coordinator(path=str(p))
    assert coord.agent_names == ["a"]
