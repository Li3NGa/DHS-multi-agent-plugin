"""deepseek_multi_agent_plugin.

A multi-agent collaboration plugin for the DeepSeek ecosystem: define a
team of agents (mock, HTTP or LLM-backed) and run them together with one
of the built-in collaboration strategies - broadcast, sequential, debate,
supervisor, consensus or relay. An HTTP adapter server, a CLI and an MCP
stdio server make the plugin easy to drive from the DeepSeek Harness or
any other MCP-capable agent host.
"""

__version__ = "0.4.5"

from .agents import Agent, AgentFactory, chat_completion
from .config import build_coordinator, load_config
from .coordinator import AgentCoordinator, DeepseekAdapter
from .history import RunHistory
from .memory import MessageStore
from . import strategies

__all__ = [
    "Agent",
    "AgentCoordinator",
    "AgentFactory",
    "DeepseekAdapter",
    "MessageStore",
    "RunHistory",
    "build_coordinator",
    "chat_completion",
    "load_config",
    "strategies",
    "__version__",
]
