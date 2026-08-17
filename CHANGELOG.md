# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
