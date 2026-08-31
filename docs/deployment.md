# 部署指南 / Deployment Guide

本插件的 HTTP 适配服务可以部署为：

1. Windows 本机服务（PowerShell 一键脚本）
2. Docker 容器（推荐给 Linux 服务器 / 云主机）
3. Linux 裸进程 + systemd（无需 Docker 的轻量方案）

三种方式跑的都是同一个 `deepseek-plugin-runner` 服务（模块路径
`deepseek_multi_agent_plugin.adapters.http`），对外暴露 `/health`、`/agents`、
`/status`、`/run`、`/runs`、`/history`、`/sessions`、`/register` 等端点
（完整列表与角色要求见 [HTTP 服务接口](http_api.md)）。

**R8 安全默认值：** loopback（`127.0.0.1` / `::1` / `localhost`）可在没有鉴权的情况下运行；
任何非 loopback 监听地址都必须配置 `--token` / `--role` / `DS_AGENT_ROLES`，否则服务拒绝启动。
仅在明确的可信私有网络场景中，才能使用 `--allow-insecure-remote` 显式关闭这一保护。

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
  `-HostBind 0.0.0.0`，并确保传递鉴权 token。

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
export DS_AGENT_TOKEN=$(openssl rand -hex 16)   # 对外监听时必需
```

### 2.2 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | 容器内监听地址；这是非 loopback 地址，因此必须配置 token/RBAC |
| `PORT` | `8000` | 容器内监听端口 |
| `CONFIG` | `/app/example_config.yaml` | YAML/JSON agent 配置路径 |
| `DEEPSEEK_API_KEY` | 无 | DeepSeek API Key（LLM Agent 必需） |
| `DS_AGENT_TOKEN` | 无 | Bearer 鉴权 token；`HOST=0.0.0.0` 时必须设置 |
| `DS_AGENT_ROLES` | 无 | JSON RBAC，例如 `{"readonly":"ro-token","admin":"admin-token"}` |

### 2.3 启动

```bash
docker compose up -d --build
docker compose ps
```

服务会监听宿主机 `8000` 端口。因为容器默认监听 `0.0.0.0`，启动前必须提供
`DS_AGENT_TOKEN` 或 `DS_AGENT_ROLES`；未提供时服务会 fail-closed 并拒绝启动。

### 2.4 健康检查与日志

```bash
docker compose ps                 # STATUS 应为 healthy
docker compose logs -f deepseek-multi-agent
curl -s http://127.0.0.1:8000/health \
  -H "Authorization: Bearer $DS_AGENT_TOKEN"
```

### 2.5 优雅停止 / 更新

```bash
docker compose stop                 # 发送 SIGTERM，服务优雅关闭
docker compose down                 # 停止并删除容器
docker compose up -d --build         # 更新镜像后重启
docker compose ps
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

如果 systemd 单元改为监听 `0.0.0.0` 或其他远程地址，必须保留 `DS_AGENT_TOKEN`
或 `DS_AGENT_ROLES`；否则 R8 安全门禁会在服务启动阶段拒绝绑定。

---

## 4. 安全建议

- 服务自带 Bearer 令牌鉴权：单令牌（`DS_AGENT_TOKEN` / `--token`，等于 admin 角色）
  或分角色令牌（`DS_AGENT_ROLES` 传 JSON 对象 `{role: token}`，或重复 `--role ROLE:TOKEN`）；
- 角色层级 readonly < user < operator < admin，端点按最低角色鉴权（见
  [HTTP 服务接口](http_api.md) 第 2 节）；
- 服务默认对非 loopback HTTP 监听地址 fail-closed；生产公网/局域网部署应配置鉴权，
  不要依赖 `--allow-insecure-remote`；
- `--allow-insecure-remote` 仅用于明确可信的私有网络、测试网或已由外层网络 ACL 完整保护的场景；
- 服务本身不提供 TLS，公网部署务必放在反向代理（Nginx / Caddy）后面；
- 监听地址默认 `127.0.0.1`，跨机调用时再开放远程地址；
- 只要服务对外可访问，就必须配置令牌鉴权（`Authorization: Bearer <token>`）；
- `DEEPSEEK_API_KEY` 通过环境变量或密钥管理注入，不要写进镜像 / 仓库；
- 长期运行的服务建议设置 `--session-ttl` 与 `--max-sessions`，防止会话内存增长；
- 生产环境建议用独立配置文件挂载，不要修改镜像内的默认配置。

---

## 5. 常见问题

**Q: Docker 容器一启动就退出？**

如果容器使用默认 `HOST=0.0.0.0`，首先检查是否提供了 `DS_AGENT_TOKEN` 或 `DS_AGENT_ROLES`。
R8 会在无鉴权的远程监听场景直接拒绝启动，这是预期行为。

**Q: 调用 `/run` 返回 401？**

请求头缺少 `Authorization: Bearer <token>`，或 token 与启动时不一致。

**Q: systemd 启动后立刻退出？**

用 `journalctl -u deepseek-multi-agent -e` 看日志；如果把 `--host` 配成了非 loopback 地址，
确认同时设置了 `DS_AGENT_TOKEN` / `DS_AGENT_ROLES`。
