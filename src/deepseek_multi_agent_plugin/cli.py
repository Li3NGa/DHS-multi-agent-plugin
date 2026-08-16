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

from .agents import AgentFactory
from .config import build_coordinator
from .coordinator import AgentCoordinator
from .strategies import STRATEGY_NAMES


def _demo_coordinator() -> AgentCoordinator:
    """Two mock agents so the CLI works without any API key."""
    coord = AgentCoordinator()
    coord.register_agent(
        AgentFactory.create_agent('mock', 'researcher', message_template='[研究员] {msg}')
    )
    coord.register_agent(
        AgentFactory.create_agent('mock', 'critic', message_template='[批评家] 我对此有异议: {msg}')
    )
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


def _print_result(result, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(f"== strategy: {result['strategy']} ==")
    for i, rec in enumerate(result["rounds"], 1):
        print(f"--- step {i} ---")
        print(json.dumps(rec, ensure_ascii=False, indent=2))
    print("== FINAL ==")
    print(result["final"])


def cmd_run(args) -> int:
    coord = _build(args)
    result = coord.run(
        args.prompt,
        strategy=args.strategy,
        rounds=args.rounds,
        judge=args.judge,
        order=args.order,
        timeout=args.timeout,
    )
    _print_result(result, args.json)
    return 0


def cmd_agents(args) -> int:
    coord = _build(args)
    for agent in coord.agents:
        print(json.dumps(agent.describe(), ensure_ascii=False))
    return 0


def cmd_serve(args) -> int:
    from .adapter_server import serve
    from .history import RunHistory
    coord = _build(args)
    session_factory = None
    if args.config:
        from .config import build_coordinator, load_config
        config = load_config(args.config)
        session_factory = lambda: build_coordinator(config=dict(config))
    elif args.demo:
        from .adapter_server import register_demo_agents

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
    parser = argparse.ArgumentParser(prog="deepseek-multi-agent",
                                     description="Multi-agent collaboration plugin for DeepSeek")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="run a multi-agent collaborative task")
    p_run.add_argument("--prompt", required=True, help="task prompt")
    p_run.add_argument("--strategy", default="auto",
                       choices=list(STRATEGY_NAMES))
    p_run.add_argument("--rounds", type=int, default=3)
    p_run.add_argument("--judge", default=None, help="agent name to act as judge (debate/consensus)")
    p_run.add_argument("--order", default=None, help="comma separated agent order (sequential)")
    p_run.add_argument("--timeout", type=float, default=None, help="per-phase timeout in seconds")
    p_run.add_argument("--config", default=None, help="YAML/JSON config file")
    p_run.add_argument("--demo", action="store_true", help="use two demo mock agents")
    p_run.add_argument("--agents", default=None, help="comma separated mock agent names")
    p_run.add_argument("--json", action="store_true", help="print full JSON result")
    p_run.set_defaults(func=cmd_run)

    p_agents = sub.add_parser("agents", help="list agents from config")
    p_agents.add_argument("--config", default=None)
    p_agents.add_argument("--demo", action="store_true")
    p_agents.add_argument("--agents", default=None)
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
    if args.command == "run" and args.order:
        args.order = [n.strip() for n in args.order.split(",") if n.strip()]
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
