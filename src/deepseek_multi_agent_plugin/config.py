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
import re
from typing import Any, Dict, Optional

from .agents import AgentFactory
from .context import ContextPolicy
from .coordinator import AgentCoordinator


def load_dsh_credentials(path: Optional[str] = None) -> Dict[str, str]:
    """Load API keys from a DSH credentials file (flat YAML: KEY: value).

    Defaults to ~/.dsh/.credentials.yaml (the DeepSeek Harness credential
    store). Any entry whose key looks like an API key (e.g. DEEPSEEK_API_KEY)
    is exported to os.environ unless already set, so LLM-backed agents work
    out of the box when the plugin is mounted inside the DSH host.

    Parsing is regex-based on purpose: no PyYAML dependency required, and
    the file only ever contains flat key/value lines. Missing files or
    unreadable lines are ignored.
    """
    path = path or os.path.join(os.path.expanduser("~"), ".dsh", ".credentials.yaml")
    exported: Dict[str, str] = {}
    if not os.path.exists(path):
        return exported
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return exported
    for key, value in re.findall(r"^\s*([A-Z0-9_]+):\s*(\S+)\s*$", text, flags=re.MULTILINE):
        if not key.endswith("API_KEY"):
            continue
        if os.environ.get(key):
            continue
        os.environ[key] = value
        exported[key] = value
    return exported


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
    context_policy = ContextPolicy.from_dict(coord_cfg.get("context"))
    cache = coord_cfg.get("cache", False)
    if isinstance(cache, str):
        cache = cache.strip().lower() in ("1", "true", "yes", "on")
    coord = AgentCoordinator(
        timeout=float(coord_cfg.get("timeout_seconds", 15.0)),
        context_policy=context_policy,
        cache=bool(cache),
    )
    for acfg in cfg.get("agents") or []:
        coord.register_agent(AgentFactory.from_config(acfg))
    if coord.cache:
        coord._apply_cache(True)
    return coord
