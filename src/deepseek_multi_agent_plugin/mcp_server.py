"""Compatibility alias for :mod:`deepseek_multi_agent_plugin.adapters.mcp`.

The MCP stdio server moved into the ``adapters`` package; this module keeps
the pre-1.1 import path (``python -m deepseek_multi_agent_plugin.mcp_server``
included) working.
"""
from .adapters.mcp import *  # noqa: F401,F403
from .adapters.mcp import main  # noqa: F401

if __name__ == "__main__":
    main()
