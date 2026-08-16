# 多 agent 开发团队协作约定（AGENT_TASKS）

本仓库由多个 agent 协作开发，本目录存放任务书与完成报告。

## 团队构成（2026-08-16 更新：仅保留 Codex）

| 角色 | 载体 | 驱动方式 | 职责 |
| --- | --- | --- | --- |
| 协调者（Coordinator） | DeepSeek Harness 会话 | 直接执行 | 任务拆分、审查合并、测试验证、tag/Release、推送 GitHub |
| Codex Agent | 本机 Codex CLI（`codex.exe exec`，DeepSeek 后端） | 协调者无头调用 | 全部开发任务（功能、工程化、质量优化） |

> 历史记录：TraeWork Agent（TRAE SOLO CN 工作模式）已于 2026-08-16 退出本团队，
> 其贡献保留在提交历史与完成报告中（relay 策略、MCP 服务、RunHistory 持久化、
> 完善度审计报告等）。

## 协作流程

1. 协调者把任务写成 `AGENT_TASKS/<agent>_task_<主题>.md`（含背景、规格、验收标准、约束、隔离范围）；
2. Codex：协调者通过 CLI 后台执行任务书（stdin 传入），完成报告落盘后停止写入，
   等待协调者验证；
3. Agent 完成后在 `AGENT_TASKS/<agent>_task_<主题>_done.md` 写完成报告（改动清单 + 测试结果）；
4. 协调者审查代码 → 修复问题 → 全量测试 → 提交推送 → 视版本打 tag/Release；
5. 并行任务必须隔离文件范围（示例：一个碰部署文件、一个碰策略文件），避免冲突。

## 约束（所有 agent 通用）

- 不得执行 `git push`（推送统一由协调者完成）；
- 不得改动任务书未授权的文件；
- 保持纯标准库实现、中文文档、既有代码风格；
- 版本号变更必须同步 `pyproject.toml` 与 `src/deepseek_multi_agent_plugin/__init__.py`。
