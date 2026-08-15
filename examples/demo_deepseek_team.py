"""演示接入真实 DeepSeek API 的多智能体辩论。

需要先设置环境变量：
    export DEEPSEEK_API_KEY=sk-xxxx        # Windows: set DEEPSEEK_API_KEY=sk-xxxx

运行方式：
    python examples/demo_deepseek_team.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from deepseek_multi_agent_plugin import AgentCoordinator, AgentFactory


def main() -> None:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("请先设置环境变量 DEEPSEEK_API_KEY")

    coord = AgentCoordinator(timeout=60.0)
    coord.register_agent(
        AgentFactory.create_agent(
            "deepseek",
            "researcher",
            role="研究员",
            system_prompt="你是一名严谨的研究员，擅长收集信息并给出有依据的分析。",
            model="deepseek-chat",
            temperature=0.3,
        )
    )
    coord.register_agent(
        AgentFactory.create_agent(
            "deepseek",
            "critic",
            role="批评家",
            system_prompt="你是一名挑剔的批评家，善于发现方案中的漏洞与风险。",
            model="deepseek-chat",
            temperature=0.7,
        )
    )
    coord.register_agent(
        AgentFactory.create_agent(
            "deepseek",
            "judge",
            role="裁判",
            system_prompt="你是一名公正的裁判，会综合各方观点给出最终结论。",
            model="deepseek-chat",
            temperature=0.2,
        )
    )

    result = coord.run(
        "AI 安全当前最重要的问题是什么？",
        strategy="debate",
        rounds=2,
        judge="judge",
    )
    for rec in result["rounds"]:
        print(rec)
    print()
    print("===== 最终结论 =====")
    print(result["final"])


if __name__ == "__main__":
    main()
