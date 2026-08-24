"""Command line interface.

Commands:

  deepseek-multi-agent run --prompt "..." [options]
  deepseek-multi-agent serve --port 8000 [--config file] [--demo]
  deepseek-multi-agent agents --config file

Examples:

  deepseek-multi-agent run --demo --strategy debate --prompt "AI 安全最重要的问题是什么" --rounds 2
  deepseek-multi-agent run --config example_config.yaml --strategy supervisor --prompt "写一份产品方案" --json
  deepseek-multi-agent serve --config example_config.yaml --port 8000
"""
import argparse
import json
import os
import sys
from typing import Optional

from ..agents import AgentFactory
from ..config import build_coordinator
from ..coordinator import AgentCoordinator
from ..strategies import STRATEGY_NAMES


def _demo_coordinator() -> AgentCoordinator:
    """Two mock agents so the CLI works without any API key.

    Reuses the HTTP server's demo team (alpha/beta) so CLI and HTTP demo
    experiences stay consistent.
    """
    from .http import register_demo_agents
    coord = AgentCoordinator()
    register_demo_agents(coord)
    return coord


def _build(args) -> AgentCoordinator:
    if args.config:
        return build_coordinator(path=args.config)
    if args.demo:
        return _demo_coordinator()
    names = [n.strip() for n in (args.agents or "").split(",") if n.strip()]
    if not names:
        raise SystemExit("no agents: pass --config FILE, --demo, or --agents a,b,c")
    coord = AgentCoordinator()
    for name in names:
        coord.register_agent(AgentFactory.create_agent('mock', name))
    return coord


def _print_result(result, as_json: bool, show_usage: bool = False,
                  show_trace: bool = False,
                  coordinator: Optional[AgentCoordinator] = None) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"== strategy: {result['strategy']} ==")
        for i, rec in enumerate(result["rounds"], 1):
            print(f"--- step {i} ---")
            print(json.dumps(rec, ensure_ascii=False, indent=2))
        print("== FINAL ==")
        print(result["final"])
        if show_usage:
            usage = (result.get("meta") or {}).get("usage")
            if usage is not None:
                print("== USAGE ==")
                print(json.dumps(usage, ensure_ascii=False, indent=2))
    if show_trace and coordinator is not None:
        run_id = (result.get("meta") or {}).get("run_id")
        trace = coordinator.runs.get(run_id) if run_id else None
        if trace is not None:
            print("== TRACE ==")
            print(json.dumps(trace.to_dict(), ensure_ascii=False, indent=2))


def cmd_run(args) -> int:
    from ..context import ContextPolicy

    coord = _build(args)
    run_kwargs = {
        "strategy": args.strategy,
        "rounds": args.rounds,
        "judge": args.judge,
        "order": args.order,
        "workers": args.workers,
        "timeout": args.timeout,
    }
    if args.context_window is not None or args.context_max_chars is not None:
        run_kwargs["context"] = ContextPolicy(
            window=args.context_window,
            max_chars=args.context_max_chars,
        )
    if args.cache:
        run_kwargs["cache"] = True
    result = coord.run(args.prompt, **run_kwargs)
    _print_result(result, args.json, show_usage=args.usage,
                  show_trace=args.trace, coordinator=coord)
    return 0


def cmd_agents(args) -> int:
    coord = _build(args)
    if args.json:
        print(json.dumps([a.describe() for a in coord.agents], ensure_ascii=False, indent=2))
        return 0
    for agent in coord.agents:
        print(json.dumps(agent.describe(), ensure_ascii=False))
    return 0


def cmd_serve(args) -> int:
    from ..history import RunHistory
    from .http import serve
    coord = _build(args)
    session_factory = None
    if args.config:
        from ..config import build_coordinator, load_config
        config = load_config(args.config)

        def session_factory():
            return build_coordinator(config=dict(config))
    elif args.demo:
        from .http import register_demo_agents

        def session_factory():
            c = AgentCoordinator()
            register_demo_agents(c)
            return c

    history = RunHistory(args.history) if args.history else None
    serve(
        args.host,
        args.port,
        coord,
        token=args.token,
        session_factory=session_factory,
        history=history,
        history_prompt_limit=args.history_prompt_limit,
        history_final_limit=args.history_final_limit,
    )
    return 0


def main(argv=None) -> int:
    from .. import __version__
    parser = argparse.ArgumentParser(prog="deepseek-multi-agent",
                                     description="Multi-agent collaboration plugin for DeepSeek")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="run a multi-agent collaborative task")
    p_run.add_argument("--prompt", required=True, help="task prompt")
    p_run.add_argument("--strategy", default="auto",
                       choices=list(STRATEGY_NAMES))
    p_run.add_argument("--rounds", type=int, default=3)
    p_run.add_argument("--judge", default=None, help="agent name to act as judge (debate/consensus)")
    p_run.add_argument("--order", default=None, help="comma separated agent order (sequential/relay)")
    p_run.add_argument("--workers", default=None, help="comma separated supervisor worker agents")
    p_run.add_argument("--timeout", type=float, default=None, help="per-phase timeout in seconds")
    p_run.add_argument("--context-window", type=int, default=None,
                       help="keep only the most recent N history messages (default: off)")
    p_run.add_argument("--context-max-chars", type=int, default=None,
                       help="truncate each history message to N chars (default: off)")
    p_run.add_argument("--cache", action="store_true",
                       help="enable the in-process LLM response cache")
    p_run.add_argument("--usage", action="store_true",
                       help="print meta.usage summary after FINAL (non-JSON mode)")
    p_run.add_argument("--trace", action="store_true",
                       help="print the run trace (spans + tasks) after the result")
    p_run.add_argument("--config", default=None, help="YAML/JSON config file")
    p_run.add_argument("--demo", action="store_true", help="use two demo mock agents")
    p_run.add_argument("--agents", default=None, help="comma separated mock agent names")
    p_run.add_argument("--json", action="store_true", help="print full JSON result")
    p_run.set_defaults(func=cmd_run)

    p_agents = sub.add_parser("agents", help="list agents from config")
    p_agents.add_argument("--config", default=None)
    p_agents.add_argument("--demo", action="store_true")
    p_agents.add_argument("--agents", default=None)
    p_agents.add_argument("--json", action="store_true", help="print a single JSON array")
    p_agents.set_defaults(func=cmd_agents)

    p_serve = sub.add_parser("serve", help="run the HTTP adapter server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--config", default=None)
    p_serve.add_argument("--demo", action="store_true")
    p_serve.add_argument("--agents", default=None)
    p_serve.add_argument("--token", default=os.environ.get("DS_AGENT_TOKEN"),
                         help="require 'Authorization: Bearer <token>' (default: $DS_AGENT_TOKEN)")
    p_serve.add_argument("--history", default=os.environ.get("DS_HISTORY_FILE"),
                         help="run history JSONL file (default: $DS_HISTORY_FILE; unset = disabled)")
    p_serve.add_argument("--history-prompt-limit", type=int, default=None,
                         help="truncate persisted prompts to N chars (default: no truncation)")
    p_serve.add_argument("--history-final-limit", type=int, default=None,
                         help="truncate persisted final answers to N chars (default: no truncation)")
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    if args.command == "run":
        if args.order:
            args.order = [n.strip() for n in args.order.split(",") if n.strip()]
        if args.workers:
            args.workers = [n.strip() for n in args.workers.split(",") if n.strip()]
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
