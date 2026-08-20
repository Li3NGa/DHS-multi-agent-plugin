"""Compatibility alias for :mod:`deepseek_multi_agent_plugin.adapters.cli`.

The CLI moved into the ``adapters`` package; this module keeps the pre-1.1
import path (``python -m deepseek_multi_agent_plugin.cli`` included) working.
"""
from .adapters.cli import *  # noqa: F401,F403
from .adapters.cli import main  # noqa: F401

if __name__ == "__main__":
    raise SystemExit(main())
