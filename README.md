<div align="center">

![DHS Multi-Agent](docs/assets/banner.jpg)

# DHS Multi-Agent Orchestration

[![CI](https://github.com/Li3NGa/DHS-multi-agent-plugin/actions/workflows/ci.yml/badge.svg)](https://github.com/Li3NGa/DHS-multi-agent-plugin/actions/workflows/ci.yml)
[![Native Runtime](https://github.com/Li3NGa/DHS-multi-agent-plugin/actions/workflows/native-runtime.yml/badge.svg)](https://github.com/Li3NGa/DHS-multi-agent-plugin/actions/workflows/native-runtime.yml)
[![npm](https://img.shields.io/npm/v/dhs-multi-agent.svg)](https://www.npmjs.com/package/dhs-multi-agent)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![DeepSeek](https://img.shields.io/badge/DeepSeek-4D6BFE?logo=deepseek&logoColor=white)](https://www.deepseek.com/)

**将 DeepSeek Harness 变成强大的多智能体编排引擎**

[快速开始](#-快速开始) ·
[核心特性](#-核心特性) ·
[架构概览](#-架构概览) ·
[文档](#-文档) ·
[示例](#-示例)

</div>

---

## ✨ 核心特性

### 🧠 智能规划与路由
- **Planner** — 从自然语言意图生成结构化任务图
- **Validator** — 严格的计划验证，拒绝不安全或格式错误的计划
- **AgentRouter** — 基于能力的智能体路由，支持显式分配和自动匹配

### ⚡ DAG 并行调度
- 真正的有向无环图执行，独立任务自动并发
- 保留依赖关系的同时最大化并行度
- 支持任意复杂的任务依赖拓扑

### 🛡️ 有界容错恢复
- **Retry** — 超时失败在预算内自动重试
- **Repair** — 不可用智能体自动从路由池中移除
- **Replan** — 依赖失败触发确定性重规划
- **Abort** — 取消操作永不触发恢复

### 📊 运行时可观测性
- `RuntimeDiagnostics` — 运行时诊断指标
- `RunRegistry` — 运行注册与状态追踪
- Metrics 收集 + Observer 模式
- 无需数据库的内存内诊断

### 🔒 企业级安全
- RBAC 角色层次访问控制
- HMAC 时序安全令牌认证
- CSRF 防护与输入验证
- 敏感信息自动脱敏

### 🎯 多种协作策略
- **Sequential** — 顺序串行执行
- **Broadcast** — 广播并行执行
- **Relay** — 接力式传递
- **DAG** — 任意依赖图直接执行

---

## 🏗️ 架构概览

```text
用户意图 / 任务计划
        │
        ▼
     Planner  ◄─────────────────────────┐
        │                               │
        ▼                               │
    Validator                          │
        │                               │
        ▼                               │
      Router                           │
        │                               │
        ├─────────────┐                 │
        │             │                 │
        ▼             ▼                 │
   Supervisor    Direct DAG             │
        │             │                 │
        ▼             ▼                 │
    Strategy     Scheduler              │
        │             │                 │
        └──────┬──────┘                 │
               │                        │
               ▼                        │
          AgentRunner                   │
               │                        │
               ▼                        │
           Real DSH                     │
               │                        │
               ▼                        │
      Recovery / Diagnostics ───────────┘
```

---

## 🚀 快速开始

### 安装

```bash
npm install dhs-multi-agent
```

> 需要 Node.js `>=22.14.0` 和提供 DeepSeek Harness / Cordis 运行时的宿主环境。

### 最小示例

```typescript
import { apply } from 'dhs-multi-agent'

// 注册插件
apply(ctx, {
  concurrency: 4,
  defaultTimeoutMs: 60_000,
})

// 运行 DAG 任务
const result = await ctx.multiAgent.runDag([
  {
    id: 'research',
    agentId: 'researcher',
    prompt: '收集相关事实。',
  },
  {
    id: 'review',
    agentId: 'critic',
    prompt: '审查研究结果。',
    dependsOn: ['research'],
  },
])
```

### 带恢复的编排

```typescript
const result = await ctx.multiAgent.runWithRecovery(plan, {
  runId: 'run-1',
  input: '用户意图',
  agents: [
    { id: 'researcher', capabilities: ['research'] },
    { id: 'writer', capabilities: ['writing'] },
  ],
  recovery: { maxAttempts: 3, maxReplans: 2 },
})
```

---

## 📦 公共 API

```typescript
import {
  // 核心运行时
  AgentRunner,
  Scheduler,
  Task,
  TaskGraph,
  // 策略
  runSequential,
  runBroadcast,
  runRelay,
  runDag,
  // Supervisor
  Supervisor,
  createSupervisor,
  // 恢复
  createRecoveryManager,
  // 诊断
  RuntimeDiagnostics,
  RunRegistry,
  createRuntimeDiagnostics,
  // 插件入口
  apply,
} from 'dhs-multi-agent'
```

---

## 📚 文档

| 文档 | 说明 |
|------|------|
| [使用指南](docs/usage.md) | 详细使用说明和配置选项 |
| [API 参考](docs/api_reference.md) | 完整的 API 文档 |
| [运行时 API](docs/runtime-api.md) | Native 运行时 API |
| [策略说明](docs/strategies.md) | 各协作策略的详细介绍 |
| [Supervisor 契约](docs/supervisor-api.md) | Supervisor 接口规范 |
| [部署指南](docs/deployment.md) | 生产环境部署 |
| [HTTP API](docs/http_api.md) | Python HTTP 服务接口 |
| [MCP 集成](docs/mcp.md) | MCP 协议支持 |
| [架构决策记录](docs/adr/) | 重要设计决策的记录 |
| [真相来源](docs/source-of-truth.md) | 代码库结构说明 |

---

## 💡 示例

### Python 示例

```bash
# 演示全部 5 种协作策略（无需 API Key）
python examples/demo_strategies.py

# 真实 DeepSeek 三人辩论
DEEPSEEK_API_KEY=sk-xxx python examples/demo_deepseek_team.py

# 启动 HTTP 服务
python examples/run_http_server.py
```

更多示例请查看 [examples/](examples/) 目录。

---

## 🧪 测试

```bash
# TypeScript 单元测试
pnpm --dir packages/dsh-multi-agent test

# 类型检查
pnpm --dir packages/dsh-multi-agent typecheck

# 构建
pnpm --dir packages/dsh-multi-agent build

# Smoke 测试
pnpm test:smoke

# Python 测试
pytest tests/ -q
```

**测试覆盖：**
- TypeScript：164+ 单元测试
- Python：386+ 测试用例
- 包含集成测试、Smoke 测试、安全测试

---

## 🏛️ 仓库结构

```text
DHS-multi-agent-plugin/
├── packages/dsh-multi-agent/    # Native 生产源代码（TypeScript）
│   ├── src/                      #   运行时核心
│   │   ├── planner/              #   规划器
│   │   ├── supervisor/           #   Supervisor
│   │   ├── recovery/             #   恢复机制
│   │   ├── strategies/           #   协作策略
│   │   └── ...
│   └── tests/                    #   测试套件
├── src/deepseek_multi_agent_plugin/  # Python 运行时
│   ├── runtime/                  #   核心运行时
│   ├── adapters/                 #   CLI/HTTP/MCP 适配器
│   └── ...
├── docs/                         # 文档
│   ├── adr/                      #   架构决策记录
│   └── ...
├── scripts/                      # 发布和验证脚本
├── examples/                     # 示例代码
├── cordis.patch.yml              # DSH Bundle Patch
└── ...
```

---

## 🤝 贡献

欢迎贡献！请查看以下资源：

- 提交 Issue：[GitHub Issues](https://github.com/Li3NGa/DHS-multi-agent-plugin/issues)
- 安全问题：请参阅 [安全策略](.github/SECURITY.md)
- 代码规范：遵循现有代码风格，添加测试

---

## 📄 许可证

[MIT License](LICENSE)

---

<div align="center">

**如果这个项目对你有帮助，欢迎给个 ⭐ Star**

Made with ❤️ for the DeepSeek ecosystem

</div>
