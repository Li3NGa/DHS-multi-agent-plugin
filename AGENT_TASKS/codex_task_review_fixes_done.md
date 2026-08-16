# Codex 审查问题修复完成报告（P1 / P2 / P3）

> 任务：完善审查结论中的 1 个 P1、2 个 P2、4 个 P3 · 完成时间：2026-08-16 · 状态：待协调者审查

## P1：文档与分发实况不符

- README / docs/usage.md 不再宣称“已发布到 PyPI”，改为“当前尚未发布到 PyPI，从 Git 安装（固定 v0.4.6 tag）”，并注明配置 `PYPI_API_TOKEN` 后可切换 `pip install`。
- docs/publishing.md 顶部新增“当前状态”警告：尚未实际分发到 PyPI，本文档是流程说明；版本示例统一为 v0.4.6。
- RELEASE_NOTES.md 顶部补充历史说明，避免读者误以为 v0.4.2 是当前版本。

## P2-1：文档一致性

- README 英文简介补充 `relay` 策略；Features 由“三种使用方式”改为“四种使用方式”（Python API / CLI / HTTP / MCP）。
- README 文档链接补充 MCP 服务器与部署指南。
- docs/usage.md 与 publishing.md 的“三种方式”同步为“四种方式”。
- CLI demo 说明由 researcher/critic 更新为 alpha/beta（与 HTTP demo 一致）。

## P2-2：CLI 参数缺口

- `run` 子命令新增 `--workers`（逗号分隔的 supervisor 工人 Agent），与 Python API / HTTP / MCP 对齐。
- `--order` 帮助文本补充 relay 也支持顺序参数。

## P3：边角体验（4 项）

1. `agents` 子命令新增 `--json`，输出单个 JSON 数组，便于脚本解析。
2. CLI `--demo` 与 HTTP `register_demo_agents` 统一为 alpha/beta，消除两套 demo 名称。
3. HTTP `/register` 配置错误（如空 agent 配置）由 500 改为明确的 400 `invalid agent config`；任意事件错误统一返回 400。
4. MCP stdio 对非法 JSON 行返回 JSON-RPC `-32700 Parse error`，非对象请求返回 `-32600 Invalid Request`，不再静默丢弃。

## 测试结果

`.venv\Scripts\python.exe -m pytest -q` → **127 passed**（原 124 + 新增 3：agents --json、run --workers help、register 400），0 failed。

## 约束

- 未改动 `dsh/`、`deploy/`、Docker 文件、`.github/workflows/*`；
- 未执行 `git push`；未引入调试产物；
- 既有 HTTP 端点路径与字段、MCP 工具名与 inputSchema、`run()` 结果结构保持不变。
