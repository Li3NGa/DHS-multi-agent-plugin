"""Agent abstraction and factory.

An Agent is a named collaborator with an optional role and system
prompt plus exactly one *backend*:

* a plain Python handler callable (mock/echo/custom logic), or
* an LLM provider (deepseek / openai) called over HTTP with the
  OpenAI-compatible /chat/completions protocol (stdlib only, no SDK
  required), or
* a remote http endpoint the agent POSTs JSON messages to, or
* an external command-line program (cli) that receives the message as
  its last argument and returns its stdout/stderr.

AgentFactory builds agents from kind strings or config dicts so that
YAML/JSON configuration can describe whole agent teams.
"""
import json
import math
import os
import random
import subprocess
import time
from threading import Lock
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Optional
from urllib import error as urlerror
from urllib import request

from .cache import ResponseCache, request_fingerprint
from .memory import MessageStore

# --------------------------------------------------------------------------
# LLM chat completion over OpenAI-compatible HTTP (stdlib only)
# --------------------------------------------------------------------------
# HTTP statuses worth retrying (rate limit + transient server errors).
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_BACKOFF_SECONDS = 8.0


def _max_backoff_seconds() -> float:
    """重试退避上限：默认 MAX_BACKOFF_SECONDS，可用环境变量覆盖。

    DSMA_MAX_BACKOFF_SECONDS 解析失败或为非法非正值（含 NaN/Inf）时，
    静默回退默认值，避免配置错误导致退避失效或线程异常阻塞。
    """
    raw = os.environ.get("DSMA_MAX_BACKOFF_SECONDS")
    if raw is None:
        return MAX_BACKOFF_SECONDS
    try:
        value = float(raw.strip())
    except ValueError:
        return MAX_BACKOFF_SECONDS
    if not math.isfinite(value) or value <= 0:
        return MAX_BACKOFF_SECONDS
    return value


def _retry_delay(attempt: int, backoff: float, max_backoff: float) -> float:
    """第 attempt 次重试的全抖动（full jitter）延迟。

    上限为指数退避 min(backoff * 2**attempt, max_backoff)，在 [0, 上限] 内
    均匀随机采样，避免大量客户端在同一时刻扎堆重试（雷群效应）。
    """
    cap = min(backoff * (2 ** attempt), max_backoff)
    return random.uniform(0.0, cap)


def chat_completion(
    base_url: str,
    api_key: str,
    model: str,
    messages: List[Dict[str, str]],
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout: float = 60.0,
    retries: int = 2,
    backoff: float = 0.5,
    response_format: Optional[Dict[str, Any]] = None,
    return_usage: bool = False,
    cache: Optional[ResponseCache] = None,
) -> Any:
    """Call POST {base_url}/chat/completions and return the reply text.

    Transient failures (HTTP 429/5xx, connection/timeout errors) are retried
    up to ``retries`` times with full-jitter exponential backoff, whose ceiling
    defaults to ``MAX_BACKOFF_SECONDS`` and can be overridden via the
    ``DSMA_MAX_BACKOFF_SECONDS`` environment variable.

    With ``return_usage=True`` returns ``{"content": str, "usage": dict}``
    instead of just the content string, so callers can track token usage.
    ``response_format`` (e.g. ``{"type": "json_object"}``) is forwarded to the
    API verbatim for structured-output mode.

    With ``cache`` set, successful responses are cached keyed by a
    fingerprint over every reply-affecting parameter (base_url, model,
    messages, temperature, max_tokens, response_format); a cache hit
    returns immediately without any HTTP call, and with ``return_usage=True``
    its usage dict is marked ``{"cache_hit": True}`` (all token counters
    zero).
    """
    cache_key = None
    if cache is not None:
        digest = request_fingerprint(
            provider=base_url,
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        cached = cache.get(digest)
        if cached is not None:
            if return_usage:
                return {
                    "content": cached,
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                        "cache_hit": True,
                    },
                }
            return cached
        cache_key = digest

    url = base_url.rstrip("/") + "/chat/completions"
    payload: Dict[str, Any] = {"model": model, "messages": messages}
    if temperature is not None:
        payload["temperature"] = float(temperature)
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)
    if response_format is not None:
        payload["response_format"] = response_format
    body: Dict[str, Any] = {}
    max_backoff = _max_backoff_seconds()
    for attempt in range(max(0, retries) + 1):
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + api_key,
            },
        )
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                try:
                    body = json.loads(resp.read().decode("utf-8"))
                except ValueError:
                    if attempt < retries:
                        time.sleep(_retry_delay(attempt, backoff, max_backoff))
                        continue
                    raise
            break
        except urlerror.HTTPError as exc:
            if exc.code in RETRYABLE_STATUS and attempt < retries:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                delay = _retry_delay(attempt, backoff, max_backoff)
                retry_after_seconds = None
                if retry_after is not None:
                    try:
                        retry_after_seconds = float(retry_after)
                    except ValueError:
                        pass  # 非数字 Retry-After（如 HTTP-date）无法解析：仅用抖动延迟
                if retry_after_seconds is not None:
                    # Retry-After 是服务端要求的最低等待时间，先与全抖动延迟取
                    # max，再直接封顶在 max_backoff。这里不选择再乘 0.5~1.0
                    # 抖动：乘法抖动可能把实际睡眠压到 Retry-After 之下，违背
                    # 服务端意图；封顶则可避免异常大的 Retry-After 让线程长
                    # 时间阻塞（与旧实现 min(...) 封顶行为保持一致）。
                    delay = min(max(delay, retry_after_seconds), max_backoff)
                time.sleep(delay)
                continue
            raise
        except (urlerror.URLError, TimeoutError, OSError):
            if attempt < retries:
                time.sleep(_retry_delay(attempt, backoff, max_backoff))
                continue
            raise
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        content = json.dumps(body, ensure_ascii=False)
    if return_usage:
        if cache is not None and cache_key is not None:
            cache.put(cache_key, content)
        usage = body.get("usage") or {}
        return {
            "content": content,
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0) or 0,
                "completion_tokens": usage.get("completion_tokens", 0) or 0,
                "total_tokens": usage.get("total_tokens", 0) or 0,
            },
        }
    if cache is not None and cache_key is not None:
        cache.put(cache_key, content)
    return content


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
        retries:
            How many times transient LLM call failures (429/5xx, connection
            errors) are retried with exponential backoff.
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
        retries: int = 2,
        memory: Optional[MessageStore] = None,
        timeout: float = 60.0,
        cache: bool = False,
        capabilities: Optional[Iterable[str]] = None,
    ):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.provider = (provider or "").lower() or None
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.api_key = api_key
        self.base_url = base_url
        self.retries = int(retries)
        self.timeout = timeout
        self.capabilities = as_capabilities(capabilities)
        self.cache = bool(cache)
        self._cache: Optional[ResponseCache] = ResponseCache() if self.cache else None
        self.cache_hits = 0
        self.memory = memory if memory is not None else MessageStore()
        self.total_usage: Dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        self._usage_lock = Lock()
        self._handler = handler
        if self.provider and self.provider not in self.PROVIDER_DEFAULTS:
            raise ValueError(
                f"Unknown provider '{provider}' (supported: {sorted(self.PROVIDER_DEFAULTS)})"
            )
        self.model = model or (self.PROVIDER_DEFAULTS[self.provider]["model"] if self.provider else None)

    # -- backend plumbing ---------------------------------------------------
    def _add_usage(self, usage: Dict[str, int]) -> None:
        with self._usage_lock:
            for key, value in usage.items():
                self.total_usage[key] = self.total_usage.get(key, 0) + (value or 0)

    def _provider_chat(
        self,
        messages: List[Dict[str, str]],
        response_format: Optional[Dict[str, Any]] = None,
    ) -> str:
        defaults = self.PROVIDER_DEFAULTS[self.provider]
        key = self.api_key or os.environ.get(defaults["env_key"])
        if not key:
            raise RuntimeError(
                f"agent '{self.name}': missing API key ({defaults['env_key']} or api_key=...)"
            )
        url = self.base_url or defaults["base_url"]
        out = chat_completion(
            base_url=url,
            api_key=key,
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
            retries=self.retries,
            response_format=response_format,
            return_usage=True,
            cache=self._cache,
        )
        if out["usage"].get("cache_hit"):
            with self._usage_lock:
                self.cache_hits += 1
        else:
            self._add_usage(out["usage"])
        return out["content"]

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

    def chat(
        self,
        messages: List[Dict[str, str]],
        response_format: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Direct provider call with a full chat message list (no injection).

        ``response_format`` is forwarded to the provider, e.g.
        ``{"type": "json_object"}`` for structured output mode.
        """
        if not self.provider:
            raise RuntimeError(f"agent '{self.name}' is not an LLM agent")
        if self.system_prompt:
            messages = [{"role": "system", "content": self.system_prompt}, *messages]
        return self._provider_chat(messages, response_format=response_format)

    def describe(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "provider": self.provider,
            "model": self.model,
            "capabilities": sorted(self.capabilities),
            "has_handler": self._handler is not None,
            "total_usage": dict(self.total_usage),
            "cache": self.cache,
            "cache_hits": self.cache_hits,
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
    - cli: external command-line agent. Kwargs command (required), args
      (default []), timeout (default 300 seconds), cwd (optional working
      directory) and encoding (default "utf-8"). The message is appended
      as the final argument to the command.
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
                retries=int(kwargs.get("retries", 2)),
                timeout=float(kwargs.get("timeout", 60.0)),
                cache=_as_bool(kwargs.get("cache", False)),
                capabilities=kwargs.get("capabilities"),
            )

        if kind == "mock":
            template = kwargs.get("message_template", "{msg}")

            def handler(msg: Any):
                try:
                    return template.format(msg=msg, name=name)
                except Exception:
                    return str(msg)

            return Agent(name, handler, role=kwargs.get("role"),
                         capabilities=kwargs.get("capabilities"))

        if kind == "echo":
            return Agent(name, lambda msg: f"{name} echo: {msg}", role=kwargs.get("role"),
                         capabilities=kwargs.get("capabilities"))

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

            return Agent(name, handler, role=kwargs.get("role"),
                         capabilities=kwargs.get("capabilities"))

        if kind == "custom":
            handler = kwargs.get("handler")
            if not callable(handler):
                raise ValueError("custom agent requires a callable 'handler' kwarg")
            return Agent(name, handler, role=kwargs.get("role"),
                         capabilities=kwargs.get("capabilities"))

        if kind == "cli":
            command = kwargs.get("command")
            if not command:
                raise ValueError("cli agent requires 'command' kwarg")
            args = list(kwargs.get("args") or [])
            timeout = float(kwargs.get("timeout", 300.0))
            cwd = kwargs.get("cwd")
            encoding = kwargs.get("encoding", "utf-8")

            def handler(msg: Any):
                try:
                    proc = subprocess.run(
                        [command, *args, str(msg)],
                        capture_output=True,
                        timeout=timeout,
                        cwd=cwd,
                        encoding=encoding,
                    )
                except subprocess.TimeoutExpired as exc:
                    raise RuntimeError(
                        f"cli agent {name} timed out after {timeout:g} seconds (超时)"
                    ) from exc
                except OSError as exc:
                    raise RuntimeError(
                        f"cli agent {name}: command not found (命令不存在): {command}"
                    ) from exc
                if proc.returncode != 0:
                    stderr = (proc.stderr or "").strip()
                    raise RuntimeError(
                        f"cli agent {name} exited {proc.returncode}: {stderr}"
                    )
                stdout = (proc.stdout or "").strip()
                if stdout:
                    return stdout
                return (proc.stderr or "").strip()

            return Agent(name, handler, role=kwargs.get("role"),
                         capabilities=kwargs.get("capabilities"))

        raise ValueError(f"Unknown agent kind: {kind} (mock|echo|http|deepseek|openai|custom|cli)")

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


def _as_bool(value: Any) -> bool:
    """宽松地把配置值解析成布尔（YAML/JSON 已是 bool；字符串兜底）。"""
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def as_capabilities(value: Any) -> FrozenSet[str]:
    """Normalize a capabilities config value into a frozenset.

    Accepts None, a single capability name, a comma-separated string, or
    any iterable of names; whitespace around names is ignored.
    """
    if value is None:
        return frozenset()
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",")]
        return frozenset(p for p in parts if p)
    return frozenset(str(p).strip() for p in value if str(p).strip())
