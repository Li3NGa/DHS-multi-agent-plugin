# ADR-0003: HTTP 加固与并发 run 限流

- 状态：已采纳
- 日期：2026-08-21
- 关联：ADR-0001（共享池饱和门卫）

## 背景

HTTP 适配服务默认面向本地开发（`127.0.0.1`，token 可选），但用户可能将其
暴露到局域网或公网（`HOST=0.0.0.0`）。审计后确认以下攻击面：

1. `Content-Length: -1`（或畸形值）会让 `rfile.read(-1)` 持续读到连接关闭，
   攻击者保持连接即可占满 worker 线程（慢速连接 DoS）。
2. 重复且冲突的 `Content-Length` 头是请求走私的经典特征。
3. `$DS_AGENT_ROLES` 中的空 token 会让“空 Bearer”通过鉴权（认证绕过）。
4. 开放模式（无 token）下，跨站 `text/plain`/表单 simple request 不触发
   CORS preflight，可让本地恶意网页触发 `/run` 消耗配额（CSRF）。
5. `Server` 响应头默认泄露 `Python/x.y.z` 版本指纹。
6. `RunHistory` 新文件按 umask（常见 0644）创建，同机其他用户可读。
7. Docker 镜像默认以 root 运行服务。
8. 大量并发 `/run` 会同时打满共享线程池与上游 LLM 配额。

## 决策

### HTTP 传输层

- 新增 `_content_length(headers)`：无头 → 0；负值 / 畸形 / 重复冲突 → 400。
  `do_POST` 与 `_read_event` 共用，先于读取 body 校验。
- `POST /run`、`POST /register` 强制 `Content-Type: application/json`
  （`text/plain` 等一律 415）。
- 覆盖 `version_string()` 返回 `DHS-Multi-Agent`，隐藏 Python / BaseHTTP 指纹。

### 认证

- `TokenAuthenticator.__init__` 拒绝空 / 空白 token（`ValueError`）。
- `_parse_roles` 对 `$DS_AGENT_ROLES` 中的空 token 启动时 `SystemExit`
  （fail-closed + 清晰报错）。

### 运行与资源

- `DeepseekAdapter` 新增有界信号量 `_run_gate`（默认 4，`--max-runs` /
  `DSMA_MAX_CONCURRENT_RUNS` 可调，`run_gate_timeout` 默认 1s）。run 事件
  超限快速失败，HTTP 层映射为 429（RFC 6585）。
- 单个 `register` 事件最多注册 `MAX_REGISTER_AGENTS = 100` 个 agent。

### 数据与部署

- `RunHistory` 新文件以 `0o600` 创建（已有文件权限不变）。
- Dockerfile 创建非 root `dsma` 用户运行服务。
- `start_run_deadline()` 将负超时钳制为 0，避免 `Future.result(timeout<0)`
  被当作无限等待。

## 影响

- 行为变化：无 token 的 JSON 客户端必须显式发送 `Content-Type: application/json`
  （多数 HTTP 客户端默认如此，urllib 带 body 时需显式设置）。
- 性能：限流门只有同时 run 数超过 4 才介入，正常负载零开销。
- 兼容性：旧模块路径、既有 token 鉴权、开放模式行为不变（仅 Content-Type
  校验新增）。

## 备选方案

- 对 `BaseHTTPRequestHandler` 设置 socket `timeout`：会误伤长耗时的 LLM run
  （响应写入阶段超时），未采纳。
- 连接级 IP 速率限制：超出本次范围（进程内服务无共享状态，适合在反向代理
  层实现）。
