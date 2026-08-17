"""deepseek_multi_agent_plugin.

A multi-agent collaboration plugin for the DeepSeek ecosystem: define a
team of agents (mock, HTTP or LLM-backed) and run them together with one
of the built-in collaboration strategies - broadcast, sequential, debate,
supervisor, consensus or relay. An HTTP adapter server, a CLI and an MCP
stdio server make the plugin easy to drive from the DeepSeek Harness or
any other MCP-capable agent host.
"""

__version__ = "1.0.1"

from . import strategies
from .agents import Agent, AgentFactory, ResponseCache, chat_completion
from .config import build_coordinator, load_config
from .context import ContextPolicy, build_context, truncate
from .coordinator import AgentCoordinator, DeepseekAdapter
from .history import RunHistory
from .memory import MessageStore
from .observability import RunRegistry, Span, Task, Trace

__all__ = [
    "Agent",
    "AgentCoordinator",
    "AgentFactory",
    "ContextPolicy",
    "DeepseekAdapter",
    "MessageStore",
    "ResponseCache",
    "RunHistory",
    "RunRegistry",
    "Span",
    "Task",
    "Trace",
    "build_coordinator",
    "build_context",
    "chat_completion",
    "load_config",
    "truncate",
    "strategies",
    "__version__",
]
