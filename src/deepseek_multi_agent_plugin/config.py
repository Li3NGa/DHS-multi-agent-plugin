"""Configuration loading and coordinator construction.

A config file (YAML or JSON) describes the agent team and coordinator
defaults::

    coordinator:
      strategy: debate
      rounds: 3
      timeout_seconds: 15
    agents:
      - name: researcher
        kind: deepseek
        role: 研究员
        model: deepseek-chat
      - name: critic
        kind: mock
        message_template: 批评: {msg}

PyYAML is an optional dependency (only needed for .yaml/.yml files);
JSON configs work with the standard library alone.
"""
import json
import os
from typing import Any, Dict, Optional

from .agents import AgentFactory
from .coordinator import AgentCoordinator


def load_config(path: str) -> Dict[str, Any]:
    """Load a YAML or JSON config file into a plain dict."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".yaml", ".yml"):
        try:
            import yaml  # optional dependency
        except ImportError as exc:
            raise ImportError("PyYAML is required for YAML configs: pip install pyyaml") from exc
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    elif ext == ".json":
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        raise ValueError(f"unsupported config extension: {ext} (use .yaml/.yml/.json)")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("config root must be a mapping")
    return data


def build_coordinator(
    config: Optional[Dict[str, Any]] = None,
    *,
    path: Optional[str] = None,
) -> AgentCoordinator:
    """Build a coordinator from a config dict or file path.

    Registers every agent in config["agents"]; coordinator defaults come
    from config["coordinator"].
    """
    if config is None and path is not None:
        config = load_config(path)
    cfg: Dict[str, Any] = config if config is not None else {}
    coord_cfg = cfg.get("coordinator") or {}
    coord = AgentCoordinator(timeout=float(coord_cfg.get("timeout_seconds", 15.0)))
    for acfg in cfg.get("agents") or []:
        coord.register_agent(AgentFactory.from_config(acfg))
    return coord
