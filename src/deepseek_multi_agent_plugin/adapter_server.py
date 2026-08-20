"""Compatibility alias for :mod:`deepseek_multi_agent_plugin.adapters.http`.

The HTTP adapter moved into the ``adapters`` package; this module keeps
the pre-1.1 import path (``python -m deepseek_multi_agent_plugin.adapter_server``
included) working.
"""
from .adapters.http import *  # noqa: F401,F403
from .adapters.http import _parse_roles, main  # noqa: F401

if __name__ == "__main__":
    main()
