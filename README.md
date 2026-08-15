# deepseek-multi-agent-plugin

A starter plugin that enables multi-agent coordination and an adapter for the Deepseek harness.

Goals
- Provide a lightweight AgentCoordinator for orchestrating multiple agents
- Provide an AgentFactory to create mock/http/custom agents (see src/deepseek_multi_agent_plugin/agents.py)
- Provide a DeepseekAdapter and an HTTP adapter server so Deepseek harnesses can call into the plugin
- Ship a minimal Python package, tests, and CI

AgentFactory
- Location: src/deepseek_multi_agent_plugin/agents.py
- Supported kinds: mock, http, custom
- For production LLMs, implement a 'custom' handler that wraps your LLM SDK (OpenAI, HuggingFace, LangChain, etc.)

Deepseek adapter (HTTP)
The package exposes a small HTTP server that accepts POST /run JSON events and returns JSON responses. This avoids adding runtime dependencies so the adapter is easy to deploy.

Example event payload:
{
  "type": "run",
  "prompt": "Summarize the issue",
  "rounds": 3
}

Response example:
{
  "history": [ ... ]
}

Run locally (demo agents registered):

  python -m deepseek_multi_agent_plugin.adapter_server --port 8000 --demo

Or when installed from the package (console script provided):

  deepseek-plugin-runner --port 8000 --demo

Packaging and publishing
1) Build distributables locally:
   python -m pip install --upgrade build
   python -m build
   # artifacts will be in the dist/ folder

2) Install locally for testing:
   python -m pip install dist/deepseek_multi_agent_plugin-0.1.0-py3-none-any.whl

3) Create GitHub repo and push (using gh CLI):
   gh repo create <your-username>/deepseek-multi-agent-plugin --public --source . --remote origin --push --confirm

4) Optional: create a GitHub release from the dist/ tarball or upload artifacts in the release

CI
- GitHub Actions workflow in .github/workflows/ci.yml runs pytest on push/PR against main branch.

Next steps / Recommendations
- Replace demo agents with real agent factories that integrate your chosen LLM provider.
- Add authentication/TLS to the adapter when exposing it externally.
- Add more comprehensive tests and example configs that match Deepseek harness expectations.

Contact
- Review the code in src/deepseek_multi_agent_plugin and run the tests locally. If you'd like, provide your GitHub username and I can produce exact commands to push and (optionally) create the remote repo for you.