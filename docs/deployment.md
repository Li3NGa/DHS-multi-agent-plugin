# 部署指南 / Deployment Guide

本插件的 HTTP 适配服务可以部署为：

1. Windows 本机服务（PowerShell 一键脚本）
2. Docker 容器（推荐给 Linux 服务器 / 云主机）
3. Linux 裸进程 + systemd（无需 Docker 的轻量方案）

三种方式跑的都是同一个 `deepseek-plugin-runner` 服务，对外暴露
`/health`、`/agents`、`/run`、`/register` 四个端点。

---

## 1. Windows 本机部署

仓库根目录的 `deploy/` 提供了三个脚本：

```powershell
cd C:\path\to\deepseek-multi-agent-plugin
.\deploy\install.ps1          # 创建 venv、安装包、跑测试
.\deploy\start_server.ps1 -Port 8000
.\deploy\stop_server.ps1
```

`start_server.ps1` 的行为：

- 自动从 `~/.dsh/.credentials.yaml` 或环境变量 `DEEPSEEK_API_KEY` 读取 API Key；
- 自动生成 / 复用 32 位鉴权 token，保存在
  `%LOCALAPPDATA%\deepseek-multi-agent-plugin\token.txt`；
- 后台隐藏窗口启动服务，PID 写入仓库根目录 `.server.pid`；
- 默认只监听 `127.0.0.1`；需要局域网访问时用
  `-HostBind 0.0.0.0`（务必配合 token 鉴权）。

验证：

```powershell
$token = (Get-Content "$env:LOCALAPPDATA\deepseek-multi-agent-plugin\token.txt" -Raw).Trim()
Invoke-RestMethod -Uri http://127.0.0.1:8000/health -Headers @{ Authorization = "Bearer $token" }
```

### 1.2 开机自启（Windows 任务计划程序）

把服务注册为开机启动任务（以当前用户身份运行，开机时启动、系统重启后自动拉起）：

```powershell
schtasks /Create /TN "DeepSeekMultiAgent" /SC ONSTART /RU $env:USERNAME /RL LIMITED `
  /TR "powershell -NoProfile -ExecutionPolicy Bypass -File C:\path\to\deepseek-multi-agent-plugin\deploy\start_server.ps1"
```

如需手动停止任务：

```powershell
schtasks /End /TN "DeepSeekMultiAgent"
```

---

## 2. Docker 部署

仓库自带 `Dockerfile` 与 `docker-compose.yml`。

### 2.1 准备 API Key

```bash
export DEEPSEEK_API_KEY=sk-xxxxxx
export DS_AGENT_TOKEN=$(openssl rand -hex 16)   # 可选，强烈建议设置
```

### 2.2 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | 容器内监听地址 |
| `PORT` | `8000` | 容器内监听端口 |
| `CONFIG` | `/app/example_config.yaml` | 配置文件路径 |
| `DEEPSEEK_API_KEY` | 无 | DeepSeek API Key（LLM Agent 必需） |
| `DS_AGENT_TOKEN` | 无 | Bearer 鉴权 token（对外开放时必须设置） |

### 2.3 启动

```bash
docker compose up -d --build
docker compose ps
```

服务会监听宿主机 `8000` 端口，配置从宿主机
`./example_config.yaml` 挂载进容器（只读），替换成你自己的团队配置即可。

### 2.4 健康检查与日志

```bash
docker compose ps                 # STATUS 应为 healthy
docker compose logs -f deepseek-multi-agent
curl -s http://127.0.0.1:8000/health \
  -H "Authorization: Bearer $DS_AGENT_TOKEN"
```

### 2.5 优雅停止 / 更新

```bash
docker compose stop               # 发送 SIGTERM，服务优雅关闭
docker compose down               # 停止并删除容器
docker compose up -d --build      # 更新镜像后重启
```

容器收到 `SIGTERM` 后会停止接收新请求、等待正在执行的任务返回，再关闭
HTTP 服务（`stop_grace_period` 默认 15 秒，可调整）。

Dockerfile 内置了 `HEALTHCHECK`（用 Python 标准库 `urllib` 请求 `/health`），
`docker compose ps` 的 STATUS 会显示 `healthy` / `unhealthy`。

---

## 3. Linux 裸进程 + systemd

不需要 Docker 时，可以用 venv + systemd 常驻：

```bash
python3 -m venv /opt/deepseek-multi-agent/.venv
/opt/deepseek-multi-agent/.venv/bin/pip install -e ".[dev]"
```

创建 `/etc/systemd/system/deepseek-multi-agent.service`：

```ini
[Unit]
Description=DeepSeek Multi-Agent Plugin HTTP Adapter
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/deepseek-multi-agent
EnvironmentFile=/etc/deepseek-multi-agent.env
ExecStart=/opt/deepseek-multi-agent/.venv/bin/deepseek-plugin-runner \
    --host 127.0.0.1 --port 8000 \
    --config /opt/deepseek-multi-agent/example_config.yaml
ExecStop=/bin/kill -TERM $MAINPID
Restart=on-failure
RestartSec=3
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
```

`/etc/deepseek-multi-agent.env` 内容示例：

```bash
DEEPSEEK_API_KEY=sk-xxxxxx
DS_AGENT_TOKEN=your-generated-token
```

启用并启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now deepseek-multi-agent
sudo systemctl status deepseek-multi-agent
```

---

## 4. 安全建议

- 服务本身不提供 TLS，公网部署务必放在反向代理（Nginx / Caddy）后面；
- 监听地址默认 `127.0.0.1`，跨机调用时再开放 `0.0.0.0`；
- 只要服务对外可访问，就必须配置 `DS_AGENT_TOKEN`（`Authorization: Bearer <token>`）；
- `DEEPSEEK_API_KEY` 通过环境变量或密钥管理注入，不要写进镜像 / 仓库；
- 生产环境建议用独立配置文件挂载，不要修改镜像内的默认配置。

---

## 5. 常见问题

**Q: 容器健康检查一直 unhealthy？**

检查 `docker compose logs`；常见原因是 `DS_AGENT_TOKEN` 不一致，或 8000 端口被宿主机占用。

**Q: 调用 `/run` 返回 401？**

请求头缺少 `Authorization: Bearer <token>`，或 token 与启动时不一致。

**Q: systemd 启动后立刻退出？**

用 `journalctl -u deepseek-multi-agent -e` 看日志；多半是 venv 路径或配置文件路径写错。
