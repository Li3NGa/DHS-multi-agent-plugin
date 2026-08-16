# 部署脚本（deploy/）

本目录提供 Windows PowerShell 一键部署脚本（Linux/Docker 部署见
[docs/deployment.md](../docs/deployment.md)，由 codex agent 补充）。

| 脚本 | 作用 |
| --- | --- |
| [install.ps1](install.ps1) | 创建 venv、安装包与开发依赖、运行全部测试 |
| [start_server.ps1](start_server.ps1) | 后台启动 HTTP 适配服务（自动加载 DeepSeek Key、自动生成鉴权 token、PID 管理） |
| [stop_server.ps1](stop_server.ps1) | 停止后台服务 |

## 快速开始

```powershell
cd deepseek-multi-agent-plugin
.\deploy\install.ps1
.\deploy\start_server.ps1 -Port 8000
.\deploy\stop_server.ps1
```

## 说明

- API Key：优先读取环境变量 `DEEPSEEK_API_KEY`，否则自动从 `~/.dsh/.credentials.yaml` 读取；
- 鉴权 token：首次启动自动生成 32 位十六进制 token，保存在
  `%LOCALAPPDATA%\deepseek-multi-agent-plugin\token.txt`，之后每次启动复用；
- 服务 PID 记录在仓库根目录 `.server.pid`（已被 .gitignore 排除）；
- 默认仅监听 `127.0.0.1`；需要局域网访问时用 `-HostBind 0.0.0.0`（务必配合 token 鉴权）。
