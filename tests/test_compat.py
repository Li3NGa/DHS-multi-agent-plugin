"""旧模块路径（adapter_server / mcp_server / cli）与 adapters/ 新路径的兼容性。"""
import deepseek_multi_agent_plugin.adapter_server as old_http
import deepseek_multi_agent_plugin.cli as old_cli
import deepseek_multi_agent_plugin.mcp_server as old_mcp
from deepseek_multi_agent_plugin.adapters import cli, http, mcp


def test_http_alias():
    assert old_http.build_server is http.build_server
    assert old_http.AdapterHandler is http.AdapterHandler
    assert old_http.register_demo_agents is http.register_demo_agents
    assert old_http.redact is http.redact


def test_mcp_alias():
    assert old_mcp.McpServer is mcp.McpServer
    assert old_mcp.main is mcp.main


def test_cli_alias():
    assert old_cli.main is cli.main
