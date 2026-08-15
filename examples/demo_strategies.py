"""演示全部 6 种协作策略（使用 mock Agent，无需 API Key）。

运行方式：
    python examples/demo_strategies.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from deepseek_multi_agent_plugin import AgentCoordinator, AgentFactory


def build_team() -> AgentCoordinator:
    coord = AgentCoordinator()
    coord.register_agent(
        AgentFactory.create_agent("mock", "researcher", message_template="[研究员] {msg}")
    )
    coord.register_agent(
        AgentFactory.create_agent("mock", "critic", message_template="[批评家] {msg}")
    )
    return coord


def show(title: str, result: dict) -> None:
    print("=" * 70)
    print(title)
    print("-" * 70)
    for i, rec in enumerate(result["rounds"], 1):
        print(f"step {i}: {rec}")
    print(f"FINAL: {result['final']}")
    print()


def main() -> None:
    prompt = "多智能体协同有什么好处？"
    coord = build_team()

    show("1) broadcast（广播讨论）", coord.run(prompt, strategy="broadcast", rounds=1))
    show(
        "2) sequential（顺序流水线）",
        coord.run(prompt, strategy="sequential", order=["critic", "researcher"]),
    )
    show(
        "3) debate（多轮辩论 + 裁判）",
        coord.run(prompt, strategy="debate", rounds=1, judge="critic"),
    )
    show(
        "4) supervisor（主管-下属）",
        coord.run(
            prompt,
            strategy="supervisor",
            supervisor="researcher",
            workers=["critic"],
        ),
    )
    show(
        "5) consensus（提案 + 投票）",
        coord.run(prompt, strategy="consensus", judge="researcher"),
    )
    show(
        "6) relay（接力迭代）",
        coord.run(prompt, strategy="relay", rounds=1, order=["researcher", "critic"]),
    )


if __name__ == "__main__":
    main()
