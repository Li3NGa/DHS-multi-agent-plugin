"""Deprecated coordinator APIs kept for backwards compatibility.

Pre-1.0 code drove the coordinator through ``broadcast()`` and
``run_cooperative_task()``; both are thin wrappers over ``run()`` now.
New code should call ``run(strategy=...)`` directly.
"""
from typing import Any, Dict, List, Optional


class LegacyCoordinatorAPI:
    """Mixin hosting the deprecated surface of AgentCoordinator."""

    def broadcast(self, message: Any, timeout: Optional[float] = None) -> Dict[str, Any]:
        from .strategies import _parallel
        return _parallel(self, message, timeout=timeout if timeout is not None else self.timeout)

    def run_cooperative_task(self, initial_prompt: str, rounds: int = 3) -> List[Dict[str, Any]]:
        result = self.run(initial_prompt, strategy="broadcast", rounds=rounds,
                          timeout=self.timeout)
        return result["rounds"]
