"""Agent factory utilities.

Provides a lightweight AgentFactory inspired by common open-source patterns: a
factory that instantiates agents of different types (mock, http, custom). This
keeps agent creation testable and pluggable for integrating real LLM backends
(e.g., OpenAI, HuggingFace, LangChain wrappers).
"""
from typing import Callable, Dict, Any, Optional
from urllib import request, parse
import json

from .coordinator import Agent


class AgentFactory:
    """Create Agent instances from simple descriptors.

    Supported types:
    - mock: returns a fixed or templated response
    - http: POSTs JSON to an HTTP endpoint and returns parsed JSON (uses urllib)
    - custom: user-provided handler callable via 'handler' kwarg

    Examples:
        AgentFactory.create_agent('mock', 'a1', message_template='echo: {msg}')
        AgentFactory.create_agent('custom', 'a2', handler=callable)

    For production LLM agents, implement a handler that calls the chosen LLM SDK
    and wrap it as a 'custom' handler here.
    """

    @staticmethod
    def create_agent(kind: str, name: str, **kwargs) -> Agent:
        kind = (kind or "").lower()
        if kind == "mock":
            template = kwargs.get("message_template", "{msg}")

            def handler(msg: Any):
                try:
                    return template.format(msg=msg)
                except Exception:
                    return str(msg)

            return Agent(name, handler)

        if kind == "http":
            url = kwargs.get("url")
            timeout = float(kwargs.get("timeout", 5.0))
            if not url:
                raise ValueError("http agent requires 'url' kwarg")

            def handler(msg: Any):
                payload = {"message": msg}
                data = json.dumps(payload).encode("utf-8")
                req = request.Request(url, data=data, headers={"Content-Type": "application/json"})
                with request.urlopen(req, timeout=timeout) as resp:
                    body = resp.read()
                    try:
                        return json.loads(body.decode("utf-8"))
                    except Exception:
                        return body.decode("utf-8")

            return Agent(name, handler)

        if kind == "custom":
            handler = kwargs.get("handler")
            if not callable(handler):
                raise ValueError("custom agent requires a callable 'handler' kwarg")
            return Agent(name, handler)

        raise ValueError(f"Unknown agent kind: {kind}")
