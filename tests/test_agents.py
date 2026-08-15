from deepseek_multi_agent_plugin import AgentFactory, AgentCoordinator


def test_mock_agent_from_factory():
    a = AgentFactory.create_agent('mock', 'm1', message_template='hello {msg}')
    assert a.handle('world') == 'hello world'


def test_custom_agent_and_coordinator():
    def upcase(msg):
        return str(msg).upper()

    a = AgentFactory.create_agent('custom', 'c1', handler=upcase)
    c = AgentCoordinator()
    c.register_agent(a)
    hist = c.run_cooperative_task('hi', rounds=1)
    assert isinstance(hist, list)
    # ensure agent response flowed into history
    assert any('HI' in str(v) for entry in hist for v in (entry.get('responses', {}).values() if isinstance(entry, dict) else []))
