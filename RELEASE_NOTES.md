# v0.4.2 Release Notes

> 历史说明：本文档是 v0.4.2 的发布说明；最新版本为 v0.4.6。
> 当前项目尚未发布到 PyPI，安装命令以 README / docs/publishing.md 为准（使用 Git 安装）。

首个正式版本发布（v0.3.0 → v0.4.2）。本仓库本身就是多智能体协作的产物：
Trae 实现功能 → 协调者审查合并 → Codex 补充能力的接力开发节奏。

## 核心能力

- **6 种协作策略**：broadcast（广播）、sequential（顺序流水线）、debate（多轮辩论+裁判）、
  supervisor（主管-下属）、consensus（提案-投票）、relay（接力迭代，新增）
- **7 类 Agent 后端**：mock / echo / http / deepseek / openai / custom / cli（外部命令行 agent 桥接，新增）
- **4 种接入方式**：Python API、CLI（deepseek-multi-agent）、HTTP 适配服务（Bearer 鉴权）、
  MCP stdio 服务器（新增，供 DSH / Codex / Claude 等宿主调用）

## 运行时加固（v0.3.0）

- 会话隔离：带 session_id 的请求路由到独立协调器（registry + 记忆隔离）
- 超时不阻塞：执行器 cancel_futures，慢 Agent 不会拖垮协作
- LLM 调用 429/5xx 指数退避重试、每 Agent token 用量统计
- 线程安全注册表、HTTP Bearer 鉴权（--token / DS_AGENT_TOKEN）

## 工程化（v0.4.x）

- Docker / docker-compose 部署 + 优雅关闭（SIGTERM/SIGINT），docs/deployment.md
- Windows 一键部署脚本（deploy/install.ps1、start_server.ps1、stop_server.ps1）
- 完整文档：usage / strategies / api_reference / http_api / mcp / deployment 六篇
- 可运行示例：demo_strategies.py（6 策略）、demo_deepseek_team.py、run_http_server.py

## 质量

- **97 个测试**全部通过；CI 矩阵 Python 3.10 / 3.11 / 3.12 全绿
- 修复：Python 3.10 下 concurrent.futures.TimeoutError 兼容（3.11 起才与内建 TimeoutError 互为别名）

## 安装

```bash
pip install git+https://github.com/Li3NGa/deepseek-multi-agent-plugin@v0.4.2

# 或克隆后开发安装
git clone https://github.com/Li3NGa/deepseek-multi-agent-plugin && cd deepseek-multi-agent-plugin
pip install -e ".[dev]"
```

## 30 秒体验

```bash
deepseek-multi-agent run --demo --strategy debate --rounds 2 --prompt "AI 安全最重要的问题是什么？"
deepseek-multi-agent serve --demo --port 8000
python -m deepseek_multi_agent_plugin.mcp_server --demo
```
