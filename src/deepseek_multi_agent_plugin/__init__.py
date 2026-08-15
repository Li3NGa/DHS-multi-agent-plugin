"""deepseek_multi_agent_plugin

Package entry points and version.
"""

__version__ = "0.1.0"

from .coordinator import AgentCoordinator, DeepseekAdapter
from .agents import AgentFactory

__all__ = ["AgentCoordinator", "DeepseekAdapter", "AgentFactory", "__version__"]
