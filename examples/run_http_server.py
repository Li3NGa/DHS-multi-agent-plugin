"""启动 HTTP 适配服务（使用两个演示 mock Agent）。

运行方式：
    python examples/run_http_server.py

然后访问：
    curl -s localhost:8000/health
    curl -s localhost:8000/agents
    curl -s -X POST localhost:8000/run -H "Content-Type: application/json" -d \
        '{"type": "run", "prompt": "你好", "strategy": "debate", "rounds": 1}'
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from deepseek_multi_agent_plugin.adapter_server import main


if __name__ == "__main__":
    # 等价于命令行：deepseek-plugin-runner --port 8000 --demo
    main(("--port", "8000", "--demo"))
