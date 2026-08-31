# DHS-multi-agent-plugin

[![CI](https://github.com/Li3NGa/DHS-multi-agent-plugin/actions/workflows/ci.yml/badge.svg)](https://github.com/Li3NGa/DHS-multi-agent-plugin/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/deepseek-multi-agent-plugin.svg)](https://pypi.org/project/deepseek-multi-agent-plugin/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)

多智能体协同运行时 / Multi-agent orchestration runtime：定义一支 Agent 团队（DeepSeek、
OpenAI 兼容 LLM、HTTP 服务、外部 CLI 命令、纯 Python 逻辑或后备链），用结构化任务图
（DAG）与六种协作策略编排它们，通过 Python API、CLI、HTTP 或 MCP stdio 使用。

> 📚 详细文档：[使用指南](docs/usage.md) · [策略详解](docs/strategies.md) ·
> [API 参考](docs/api_reference.md) · [HTTP 接口](docs/http_api.md) ·
> [MCP 服务器](docs/mcp.md) · [部署指南](docs/deployment.md) · [示例代码](examples/)
> · [Native Source of Truth](docs/source-of-truth.md) · [Runtime Matrix](docs/runtime-matrix.md)

## Overview

本项目提供一个多智能体运行时：注册一组 Agent，提交一个 prompt，运行时负责调度、
并发、超时、预算与记忆，返回带完整过程记录的结果。

### Python Runtime

Python runtime remains the compatibility-facing runtime for the Python API, CLI, HTTP and MCP surfaces. See the Python documentation for those features.

### Native DSH Runtime

The DSH/Cordis plugin is produced from:

```text
packages/dsh-multi-agent/src/
```

The Native path is:

```text
Input → Planner → Validator → Router → Supervisor → Strategy → Scheduler → AgentRunner → Real DSH → Recovery
```

The historical `dsh-native/` tree is verification-only and is not a production build target. See [docs/source-of-truth.md](docs/source-of-truth.md).

The current Native strategy boundary is `sequential`, `broadcast`, and `relay`. Arbitrary DAGs can be represented by the Planner, but unsupported shapes are currently linearized for sequential execution; true DAG-parallel execution is a future Strategy Boundary evolution.

## Python Features

- **6 种协作策略**：broadcast（并行讨论）、sequential（流水线）、debate（多轮辩论 + 裁判）、
  supervisor（任务分解 + 并行执行）、consensus（提案-投票）、relay（接力打磨）。
- **结构化任务图**：supervisor 输出 JSON TaskPlan（`tasks[].id/description/agent/depends_on`），
  由 DAG 调度器执行——无依赖的任务并行，有依赖的任务等待，支持
  `PENDING/RUNNING/SUCCESS/FAILED/TIMEOUT/CANCELLED/SKIPPED` 状态。
- **Agent 能力（capabilities）**：按任务需求匹配 agent 能力路由，而非简单轮转。
- **后备链（FallbackAgent）**：`FallbackAgent("name", [primary, backup])` 在 provider 失败时切换备用 agent / 备用 provider，用量照常计入预算。
- **预算控制**：`budget={"max_calls", "max_tokens", "max_cost", "max_seconds"}`，每次 agent 调用前预留额度，超预算立即中止。
- **会话生命周期、响应缓存、可观测性、HTTP RBAC、MCP stdio**等能力由 Python runtime 提供。

## Installation

```bash
pip install deepseek-multi-agent-plugin
```

要求 Python 3.10+。Native DSH development uses the root pnpm workspace; see `packages/dsh-multi-agent/README.md`.
