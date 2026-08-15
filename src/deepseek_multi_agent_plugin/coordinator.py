"""Agent coordination primitives and Deepseek harness adapter stub.

This file provides a minimal AgentCoordinator to register agents, send messages,
and run a cooperative task. DeepseekAdapter is a minimal stub showing where to
hook into the Deepseek harness (implement according to Deepseek's adapter API).
"""
from typing import Callable, Dict, List, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

class Agent:
    """Simple agent interface: must implement handle(message) -> response."""
    def __init__(self, name: str, handler: Callable[[Any], Any]):
        self.name = name
        self.handler = handler

    def handle(self, message: Any) -> Any:
        return self.handler(message)

class AgentCoordinator:
    """Coordinate multiple agents for collaborative tasks."""
    def __init__(self):
        self.agents: Dict[str, Agent] = {}

    def register_agent(self, agent: Agent) -> None:
        self.agents[agent.name] = agent

    def unregister_agent(self, name: str) -> None:
        self.agents.pop(name, None)

    def broadcast(self, message: Any, timeout: float = 10.0) -> Dict[str, Any]:
        """Send message to all agents in parallel and collect responses."""
        results: Dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=len(self.agents) or 1) as ex:
            futures = {ex.submit(a.handle, message): n for n, a in self.agents.items()}
            start = time.time()
            for f in as_completed(futures, timeout=timeout):
                name = futures[f]
                try:
                    results[name] = f.result()
                except Exception as e:
                    results[name] = {"error": str(e)}
            # best-effort: mark agents without responses as timed out
            elapsed = time.time() - start
            if elapsed >= timeout:
                for n in self.agents.keys():
                    results.setdefault(n, {"error": "timeout"})
        return results

    def run_cooperative_task(self, initial_prompt: str, rounds: int = 3) -> List[Dict[str, Any]]:
        """Run several rounds where agents see last messages and respond.
        Returns list of round responses.
        """
        history = [ {"round": 0, "prompt": initial_prompt} ]
        last_message = initial_prompt
        for r in range(1, rounds+1):
            responses = self.broadcast(last_message)
            history.append({"round": r, "responses": responses})
            # simple aggregation: concatenate agent outputs for next round
            parts = []
            for v in responses.values():
                if isinstance(v, dict) and "error" in v:
                    continue
                parts.append(str(v))
            last_message = "\n".join(parts) or last_message
        return history


class DeepseekAdapter:
    """Stub for Deepseek harness integration.

    Implement adapter methods according to Deepseek harness expectations, e.g.
    initializing with harness-provided callbacks, reporting progress, and
    mapping harness inputs to AgentCoordinator calls.
    """
    def __init__(self, coordinator: AgentCoordinator):
        self.coordinator = coordinator

    def handle_harness_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Translate a harness event into agent interactions and return result.
        Example event: {"type": "run", "prompt": "..."}
        """
        t = event.get("type")
        if t == "run":
            prompt = event.get("prompt", "")
            rounds = int(event.get("rounds", 3))
            return {"history": self.coordinator.run_cooperative_task(prompt, rounds)}
        return {"error": "unsupported event type"}
