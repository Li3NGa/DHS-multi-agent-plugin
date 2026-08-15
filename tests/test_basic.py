from deepseek_multi_agent_plugin import AgentCoordinator, Agent


def test_import_and_run():
    c = AgentCoordinator()

    def echo(msg):
        return f"echo: {msg}"

    a = Agent("a1", echo)
    c.register_agent(a)
    history = c.run_cooperative_task("hello", rounds=1)
    assert isinstance(history, list)
