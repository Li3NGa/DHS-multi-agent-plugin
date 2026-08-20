"""统一异常模型。

所有运行时错误继承 ``DSMAError``，同时按语义挂靠到内建异常
（ValueError / RuntimeError / KeyError），既保持 ``except ValueError``
这类既有用法兼容，又让调用方可以用单一基类捕获框架错误。
"""


class DSMAError(Exception):
    """Base class for all runtime errors."""


class StrategyError(DSMAError, ValueError):
    """Unknown or misused collaboration strategy."""


class AgentError(DSMAError, RuntimeError):
    """Agent backend misuse (missing API key, no backend configured)."""


class AgentNotFound(DSMAError, ValueError):
    """A named agent is not registered."""


class ProviderError(DSMAError, RuntimeError):
    """LLM provider call failed (after retries)."""


class PlanError(DSMAError, ValueError):
    """A structured task plan is invalid (bad shape, unknown dep, cycle)."""


class TaskError(DSMAError, RuntimeError):
    """Task execution failure inside the scheduler."""


class BudgetExceeded(DSMAError, RuntimeError):
    """Run budget (tokens / calls / time / cost) exhausted."""


class RunTimeout(DSMAError, TimeoutError):
    """Run-level deadline (``run_timeout``) exhausted."""


class SessionNotFound(DSMAError, KeyError):
    """Unknown session id."""
