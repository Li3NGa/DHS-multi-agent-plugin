"""Transport adapters around the core runtime.

The core (coordinator, strategies, runtime) knows nothing about HTTP, MCP
or the CLI; these modules are the only place where transport concerns
live, and they all talk to the same AgentCoordinator/DeepseekAdapter API:

  http.py -> threaded HTTP server (DeepSeek harness and curl users)
  mcp.py  -> MCP stdio server (JSON-RPC over stdin/stdout)
  cli.py  -> local command line interface
"""
