# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased] - 2026-08-21

### Security

- **HTTP 请求走私与 DoS 防护**：`Content-Length` 解析统一收敛到
  `_content_length()`——负值、畸形值、重复且冲突的头部一律 400 拒绝，
  杜绝 `read(-1)` 阻塞 worker（慢速连接 DoS）与歧义长度导致的请求走私。
- **认证空 token 拦截**：`TokenAuthenticator` 拒绝空/空白 token；
  `$DS_AGENT_ROLES` 中的空 token 启动时即 `SystemExit`，堵住
  “任意空 Bearer 都能通过鉴权”的绕过路径。
- **CSRF 缓解（开放模式）**：`POST /run` 与 `/register` 强制
  `Content-Type: application/json`，跨站 `text/plain`/表单 simple request
  无法再触发无鉴权服务执行 run。
- **隐藏服务器指纹**：`Server` 响应头改为 `DHS-Multi-Agent`，不再泄露
  Python / BaseHTTP 版本。
- **历史文件权限**：`RunHistory` 新文件以 `0600` 权限创建，避免同机
  其他用户读取含 prompt 与结果的记录。
- **Docker 非 root 运行**：镜像内以专用 `dsma` 用户运行服务，纵深防御
  容器逃逸风险。

### Fixed

- **负超时语义**：`start_run_deadline()` 将负 `timeout` 钳制为 0（deadline
  立即到期），避免 `Future.result(timeout<0)` 被解释为无限等待。
- **负预算上限拒绝**：`as_budget()` 对 `max_calls/max_tokens/max_cost/
  max_seconds` 的负值直接 `ValueError`，而不是静默地“预算立即耗尽”。

- **run deadline 浮点对齐**：`clamp_timeout()` 将剩余预算对齐到微秒，
  消除 `deadline - monotonic()` 的浮点尾差（如 `0.3000000000001819`）；
  `run_binds` 判定改为绝对时钟比较（`run_dl <= now + timeout + 1e-6`），
  避免两次独立减法引入的尾差翻转 RunTimeout 语义。
- **Session TTL=0 立即淘汰**：`SessionManager._evict_locked` 由
  `now - last_active > ttl` 改为 `now >= last_active + ttl`，
  `ttl=0` 在同 tick 下也能立即过期。
- **Windows 子进程输出编码**：E2E/CLI/MCP 测试为子进程设置
  `PYTHONIOENCODING=utf-8`，修复中文 Windows 下 `UnicodeDecodeError`。
- **HTTP 超大请求测试加固**：`ConnectionError`/`BrokenPipeError`
  （socket 半关闭竞态）视为服务器拒绝超大请求的等价信号。

### Added

- **并发 run 限流**：`DeepseekAdapter` 以有界信号量限制同时在跑的 run
  （`max_concurrent_runs`，默认 4；CLI `--max-runs` / env
  `DSMA_MAX_CONCURRENT_RUNS`），池满时快速失败并映射为 HTTP 429，
  保护共享线程池与上游 LLM 配额。
- **register 数量上限**：单个 `register` 事件最多注册 100 个 agent
  （`DeepseekAdapter.MAX_REGISTER_AGENTS`），防止一次授权请求撑爆内存。
- **共享池饱和门卫（P0）**：`shared_executor` 增加槽位信号量，`submit()`
  最多等待 `DSMA_POOL_SLOT_TIMEOUT`（默认 1s）获取空闲 worker，超时抛出
  `PoolSaturated`；策略与 DAG 调度器将其按超时降级（`{"error": "timeout"}`
  / `TIMEOUT` + `"pool saturated"`），杜绝慢 worker 身后无限排队。
- **CI 流水线**：`.github/workflows/ci.yml`，Linux 上跑
  ruff + mypy + pytest（Python 3.10–3.13 矩阵）。
- **静态类型门禁**：`pyproject.toml` 增加 `[tool.mypy]` 配置，
  全量修复 8 个文件的 17 个类型错误（含 `observability` 中
  `int > None` 潜在 TypeError）。
- **ADR 文档**：`docs/adr/0001`（共享池饱和门卫）、`docs/adr/0002`
  （deadline 浮点对齐）。

## [1.0.1] - 2026-08-17

### Fixed

- README 版本徽章由静态文本改为 PyPI 动态徽章
  （`shields.io/pypi/v/...`），此后发版无需再手改 README，
  版本号真正只存在于 `__version__` 单一来源。

## [1.0.0] - 2026-08-17

首个稳定版。版本号单一来源迁移至 `deepseek_multi_agent_plugin.__version__`，
`pyproject.toml` 通过 setuptools dynamic version 引用，发布产物与运行时永远一致。

### Added

- **可观测性（Observability）**
  - 每次 `coordinator.run()` 自动生成 `Trace`：`run_id`、span（每个 Agent 调用的
    耗时 / 状态 / 错误）与 task（策略步骤）三类记录。
  - `RunRegistry` 保留最近 N 次运行（默认 100，LRU），支持 `get` / `list` 回查。
  - Agent 健康计数：成功 / 超时 / 错误调用次数与平均耗时，经 `note_agent_call` 汇总。
  - HTTP 新端点 `/status`（版本 + Agent 健康汇总）与 `/runs/{run_id}`（Trace 回查）；
    MCP 新工具 `status` / `runs`。
  - `meta.run_id` 出现在所有入口（Python / CLI / HTTP / MCP）的返回结果中。
- **E2E 测试**：`tests/test_e2e.py` 覆盖 CLI / HTTP / MCP / 本地 fake LLM 全链路
  （含 token 鉴权、Content-Type 拒绝、超大请求体拒绝、trace 查询）。
- **CI 增强**：新增 lint job（ruff，规则 E/F/W/I/B）、Python 3.13 加入测试矩阵、
  build job（`python -m build` + `twine check` + wheel 安装后冒烟测试 + 产物上传）。
- **冒烟测试**：`scripts/smoke_test.py`，安装 wheel 后验证版本号、策略执行与
  MCP 协议握手。
- **打包**：新增 `deepseek-multi-agent-mcp` 入口脚本；PyPI classifiers 补全
  （Development Status 5 - Production/Stable、3.10–3.13、项目主页 / Issues /
  Changelog 元数据链接）。
- README 增加 Version 徽章与可观测性特性说明；新增仓库封面横幅。

### Changed

- 版本号动态化：删除 `pyproject.toml` 中的静态 `version`，改为
  `[tool.setuptools.dynamic] version = { attr = "..." }`。
- HTTP 服务统一安全基线：请求体大小上限、Content-Type 校验、prompt
  类型 / 长度校验、并发限流、错误信息脱敏；CLI / HTTP / MCP 三个入口的
  prompt 校验统一收敛到 `DeepseekAdapter`。
- 策略层 `_call_agent` 在并行执行器中显式传递 trace（contextvar 对工作
  线程不可见），无 trace 时零开销。

### Fixed

- `Trace.to_dict()` 与并发 `add_span` 的锁重入死锁：重构为内部无锁辅助方法。
- Python 3.9+ f-string 嵌套引号兼容问题（拆分临时变量）。

### Stats

- 197 个测试全部通过（3.10–3.13 矩阵），ruff lint 全绿，
  wheel / sdist 构建与 `twine check` 通过。

## [0.5.0] - 2026-08-16

### Added

- **上下文压缩（`ContextPolicy`）**：历史窗口保留（`max_messages`）、逐条
  消息截断（`max_chars`）、辩论中隐藏己方旧发言（`hide_self_in_debate`，
  默认关闭，不改变既有行为）。
- **LLM 响应缓存**：进程内线程安全 LRU（CLI `--cache` / `ResponseCache`），
  相同请求直接复用，节省 token。
- **Token 计量增强**：`meta.usage` 汇总为 `total` / `agents` / `cache_hits`。

### Changed

- 辩论策略汇总输入截断，缓解 O(轮数²×N) 的 token 增长。

## [0.4.8] - 2026-08-16

### Added

- 日志脱敏（API Key 等敏感字段）。
- MCP 协议版本协商。
- 首次发布到 PyPI。

### Fixed

- CI 在缺少 `PYPI_API_TOKEN` 时优雅跳过发布 job。

## [0.4.7] - 2026-08-15

### Fixed

- 评审问题 P1/P2/P3：发布产物一致性、CLI 缺口、协议边界情况。

## [0.4.6] - 2026-08-15

### Changed

- `RunHistory` 改为尾部读取（tail-read），避免大文件全量加载。
- LLM 退避增加抖动（jitter），避免雷群效应。

### Added

- CLI 端到端测试。

## [0.4.5] - 2026-08-14

### Changed

- 协议加固；策略名单一来源（消除多处硬编码）。

## [0.4.4] - 2026-08-13

### Added

- DSH 集成套件与 DSH 凭据自动加载。

## [0.4.3] - 2026-08-12

### Added

- 运行历史持久化（`RunHistory`），HTTP 与 MCP 查询端点。

## [0.4.2] - 2026-08-11

### Added

- `cli` Agent 桥接：把外部命令行 agent 接入协作。
- relay（接力迭代）策略与 MCP stdio 服务器（v0.4.1 起可用）。

## [0.3.0] - 2026-08-10

### Added

- 会话隔离（`session_id` → 独立协调器与记忆）。
- 超时不阻塞（执行器 `cancel_futures`）。
- LLM 429/5xx 指数退避重试、按 Agent token 用量统计。
- 线程安全注册表、HTTP Bearer 鉴权。

## [0.2.0] - 2026-08-09

### Added

- Docker / docker-compose 部署、优雅关闭（SIGTERM/SIGINT）。
- 六篇文档（usage / strategies / api_reference / http_api / mcp / deployment）。
- 可运行示例（6 策略 demo、DeepSeek 团队 demo、HTTP server）。

## [0.1.0] - 2026-08-08

### Added

- 初始版本：多智能体协作插件 —— 策略（broadcast / sequential / debate /
  supervisor / consensus）、CLI、HTTP 适配服务、基础测试。
