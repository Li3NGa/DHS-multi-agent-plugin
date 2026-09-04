# DHS Multi-Agent Orchestration

基于 DeepSeek Harness 的多智能体编排插件，提供任务规划、Agent 路由、DAG 调度、恢复机制和运行时诊断。

## 核心能力

- Planner：将任务意图转换为结构化任务计划
- Validator：检查任务 ID、依赖关系和计划结构
- AgentRouter：按显式 Agent、能力和轮询顺序分配任务
- Scheduler：支持 DAG、并发限制、取消和失败传播
- Supervisor：统一管理一次策略执行
- Recovery：支持重试、Agent 替换、确定性重规划和取消
- Diagnostics：提供运行状态、失败摘要和指标
- Strategies：Sequential、Broadcast、Relay、DAG

## 安装

```bash
npm install dhs-multi-agent
```

需要 Node.js `>=22.14.0`，并运行在提供 DeepSeek Harness / Cordis 的宿主环境中。

## 最小示例

```ts
import { apply } from 'dhs-multi-agent'

apply(ctx, {
  concurrency: 4,
  defaultTimeoutMs: 60_000,
})

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

## 文档

- [使用指南](docs/usage.md)
- [API 参考](docs/api_reference.md)
- [运行时 API](docs/runtime-api.md)
- [策略说明](docs/strategies.md)
- [Supervisor API](docs/supervisor-api.md)
- [部署指南](docs/deployment.md)
- [HTTP API](docs/http_api.md)
- [MCP 集成](docs/mcp.md)
- [架构决策记录](docs/adr/)

## 开发

```bash
pnpm install
pnpm --dir packages/dsh-multi-agent test
pnpm --dir packages/dsh-multi-agent typecheck
pnpm --dir packages/dsh-multi-agent build
pnpm test:smoke
pytest tests/ -q
```

Native 生产代码位于 `packages/dsh-multi-agent/`，Python 兼容运行时位于 `src/deepseek_multi_agent_plugin/`。

## 许可证

MIT
