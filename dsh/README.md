# DSH 插件社区安装指南

本目录是把 deepseek-multi-agent-plugin 发布进 DeepSeek Harness（DSH）插件体系的
安装套件。DSH 通过 profile 的 `cordis.patch.yml` 加载插件：本插件以 MCP 服务器形式
挂载后，DSH 对话中的模型可以直接调用 `mcp__multiagent__run` 等工具，让一支
多智能体团队（DeepSeek LLM）执行广播 / 辩论 / 主管 / 接力等协作任务。

## 1. 安装前提

- Python >= 3.10（Windows / Linux / macOS）；
- 已安装 DeepSeek Harness；
- （可选）DeepSeek API Key——本插件会自动从 `~/.dsh/.credentials.yaml` 读取
  `DEEPSEEK_API_KEY`，无需额外配置环境变量。

## 2. 一键安装（Windows PowerShell）

```powershell
git clone https://github.com/Li3NGa/deepseek-multi-agent-plugin
cd deepseek-multi-agent-plugin
.\dsh\install.ps1 -Profile web
```

脚本会：

1. `pip install git+https://github.com/Li3NGa/deepseek-multi-agent-plugin` 安装插件；
2. 把 `mcp-multiagent` 条目写入 `~/.dsh/profiles/web/cordis.patch.yml`（幂等，
   同名旧条目会被替换）；
3. DSH 热加载后自动重连，无需重启。

## 3. 手动安装

把 [cordis.patch.yml.example](cordis.patch.yml.example) 中的条目合并进
`~/.dsh/profiles/<profile>/cordis.patch.yml`，并把 `--config` 指向你自己的
agent 团队配置文件（可基于仓库根目录的 `example_config.yaml` 修改）。

## 4. 验证安装

- DSH 设置 → 插件：出现 `mcp-multiagent` 条目且状态为 active；
- 对话中让模型调用 `mcp__multiagent__status`（返回团队 agent 列表）；
- 让模型用 `mcp__multiagent__run` 跑一次协作任务（参数：prompt / strategy / rounds）。

## 5. 可用工具

| 工具 | 说明 |
| --- | --- |
| `mcp__multiagent__run` | 运行多智能体协作任务（6 种策略） |
| `mcp__multiagent__agents` | 列出团队成员 |
| `mcp__multiagent__register` | 动态注册 agent |
| `mcp__multiagent__status` | 状态摘要 |
| `mcp__multiagent__history` | 运行历史（需 --history 启用） |

## 6. 卸载

从 `cordis.patch.yml` 删除 `mcp-multiagent` 条目（含其上一条 `- insert:`），
再 `pip uninstall deepseek-multi-agent-plugin`。

## 7. 常见问题

- **工具没出现**：确认 profile 名正确（默认 web）；DSH 日志搜索 multiagent 看
  MCP 连接错误；手动在终端跑 `python -m deepseek_multi_agent_plugin.mcp_server --config ...` 排查。
- **调用报缺少 API Key**：检查 `~/.dsh/.credentials.yaml` 是否含
  `DEEPSEEK_API_KEY: sk-...`；或用 mock 团队（`--demo`）先验证链路。
- **想用局域网 HTTP 服务代替 stdio**：`transport: streamable-http` +
  `url: http://127.0.0.1:8000/mcp`（需另启 HTTP 适配服务），详见
  [docs/mcp.md](../docs/mcp.md)。
