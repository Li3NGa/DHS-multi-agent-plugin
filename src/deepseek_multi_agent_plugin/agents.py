"""Agent abstraction and factory.

An Agent is a named collaborator with an optional role and system
prompt plus exactly one *backend*:

* a plain Python handler callable (mock/echo/custom logic), or
* an LLM provider (deepseek / openai) called over HTTP with the
  OpenAI-compatible /chat/completions protocol (stdlib only, no SDK
  required), or
* a remote http endpoint the agent POSTs JSON messages to.

AgentFactory builds agents from kind strings or config dicts so that
YAML/JSON configuration can describe whole agent teams.
"""
import json
import os
from typing import Any, Callable, Dict, List, Optional
from urllib import request

from .memory import MessageStore


# --------------------------------------------------------------------------
# LLM chat completion over OpenAI-compatible HTTP (stdlib only)
# --------------------------------------------------------------------------
def chat_completion(
    base_url: str,
    api_key: str,
    model: str,
    messages: List[Dict[str, str]],
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout: float = 60.0,
) -> str:
    """Call POST {base_url}/chat/completions and return the reply text."""
    url = base_url.rstrip("/") + "/chat/completions"
    payload: Dict[str, Any] = {"model": model, "messages": messages}
    if temperature is not None:
        payload["temperature"] = float(temperature)
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
        },
    )
    with request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return json.dumps(body, ensure_ascii=False)


class Agent:
    """A named collaborator with a role, optional system prompt and a backend.

    Parameters
    ----------
    name:
        Unique identifier used by the coordinator and in transcripts.
    handler:
        Optional callable handler(message) -> response. When given, it
        takes precedence over provider.
    role:
        Free-form role description (e.g. "researcher", "critic").
    system_prompt:
        System instructions prepended to every LLM call of this agent.
    provider:
        LLM provider kind: "deepseek" or "openai" (OpenAI-compatible).
    model:
        Model id, e.g. "deepseek-chat" (default) or "gpt-4o-mini".
    temperature / max_tokens:
        Optional sampling parameters for LLM calls.
    api_key / base_url:
        Optional provider credentials; fall back to environment variables
        (DEEPSEEK_API_KEY / OPENAI_API_KEY) and provider defaults.
    memory:
        Optional MessageStore; a fresh one is created per agent.
    """

    PROVIDER_DEFAULTS = {
        "deepseek": {"base_url": "https://api.deepseek.com", "model": "deepseek-chat", "env_key": "DEEPSEEK_API_KEY"},
        "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "env_key": "OPENAI_API_KEY"},
    }

    def __init__(
        self,
        name: str,
        handler: Optional[Callable[[Any], Any]] = None,
        *,
        role: Optional[str] = None,
        system_prompt: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        memory: Optional[MessageStore] = None,
        timeout: float = 60.0,
    ):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.provider = (provider or "").lower() or None
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.memory = memory if memory is not None else MessageStore()
        self._handler = handler
        if self.provider and self.provider not in self.PROVIDER_DEFAULTS:
            raise ValueError(
                f"Unknown provider '{provider}' (supported: {sorted(self.PROVIDER_DEFAULTS)})"
            )
        self.model = model or (self.PROVIDER_DEFAULTS[self.provider]["model"] if self.provider else None)

    # -- backend plumbing ---------------------------------------------------
    def _provider_chat(self, messages: List[Dict[str, str]]) -> str:
        defaults = self.PROVIDER_DEFAULTS[self.provider]
        key = self.api_key or os.environ.get(defaults["env_key"])
        if not key:
            raise RuntimeError(
                f"agent '{self.name}': missing API key ({defaults['env_key']} or api_key=...)"
            )
        url = self.base_url or defaults["base_url"]
        return chat_completion(
            base_url=url,
            api_key=key,
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
        )

    # -- public API ---------------------------------------------------------
    def handle(self, message: Any, context: Optional[List[Dict[str, str]]] = None) -> Any:
        """Answer message.

        context is an optional list of OpenAI-style chat messages that are
        inserted before the current message (used by strategies to share the
        ongoing discussion with LLM-backed agents).
        """
        if self._handler is not None:
            return self._handler(message)

        if self.provider:
            messages: List[Dict[str, str]] = []
            if self.system_prompt:
                messages.append({"role": "system", "content": self.system_prompt})
            if context:
                messages.extend(context)
            messages.append({"role": "user", "content": str(message)})
            return self._provider_chat(messages)

        raise RuntimeError(f"agent '{self.name}' has no backend (no handler, no provider)")

    def chat(self, messages: List[Dict[str, str]]) -> str:
        """Direct provider call with a full chat message list (no injection)."""
        if not self.provider:
            raise RuntimeError(f"agent '{self.name}' is not an LLM agent")
        if self.system_prompt:
            messages = [{"role": "system", "content": self.system_prompt}, *messages]
        return self._provider_chat(messages)

    def describe(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "provider": self.provider,
            "model": self.model,
            "has_handler": self._handler is not None,
        }

    def __repr__(self) -> str:
        return f"Agent(name={self.name!r}, provider={self.provider!r}, model={self.model!r})"


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------
class AgentFactory:
    """Build Agent instances from kind strings or config dicts.

    Supported kinds:

    - mock: templated response. Kwarg message_template (default "{msg}")
      may use {msg} and {name}.
    - echo: returns "{name} echo: {msg}".
    - http: POSTs {"message": msg} as JSON to url and returns the
      parsed JSON body (or raw text on parse failure).
    - deepseek / openai: LLM agents over the OpenAI-compatible chat
      API. api_key kwarg or the matching environment variable is required
      at call time.
    - custom: user-supplied callable via the handler kwarg.
    """

    @staticmethod
    def create_agent(kind: str, name: str, **kwargs: Any) -> Agent:
        kind = (kind or "").lower()
        if kind in ("deepseek", "openai"):
            return Agent(
                name,
                provider=kind,
                role=kwargs.get("role"),
                system_prompt=kwargs.get("system_prompt"),
                model=kwargs.get("model"),
                temperature=kwargs.get("temperature"),
                max_tokens=kwargs.get("max_tokens"),
                api_key=kwargs.get("api_key"),
                base_url=kwargs.get("base_url"),
                timeout=float(kwargs.get("timeout", 60.0)),
            )

        if kind == "mock":
            template = kwargs.get("message_template", "{msg}")

            def handler(msg: Any):
                try:
                    return template.format(msg=msg, name=name)
                except Exception:
                    return str(msg)

            return Agent(name, handler, role=kwargs.get("role"))

        if kind == "echo":
            return Agent(name, lambda msg: f"{name} echo: {msg}", role=kwargs.get("role"))

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

            return Agent(name, handler, role=kwargs.get("role"))

        if kind == "custom":
            handler = kwargs.get("handler")
            if not callable(handler):
                raise ValueError("custom agent requires a callable 'handler' kwarg")
            return Agent(name, handler, role=kwargs.get("role"))

        raise ValueError(f"Unknown agent kind: {kind} (mock|echo|http|deepseek|openai|custom)")

    @staticmethod
    def from_config(cfg: Dict[str, Any]) -> Agent:
        """Build an agent from a config dict:

            {"name": "researcher", "kind": "deepseek", "model": "deepseek-chat", ...}

        kind defaults to custom when a handler is present and to
        mock otherwise.
        """
        cfg = dict(cfg)
        name = str(cfg.pop("name"))
        kind = cfg.pop("kind", None)
        if kind is None:
            kind = "custom" if callable(cfg.get("handler")) else "mock"
        return AgentFactory.create_agent(kind, name, **cfg)

    @staticmethod
    def from_configs(configs: List[Dict[str, Any]]) -> List[Agent]:
        return [AgentFactory.from_config(c) for c in configs]
