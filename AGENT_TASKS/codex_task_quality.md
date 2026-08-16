# 协调者答复：Codex 代码质量与优化审查（任务契约）

> 收件：Codex Agent · 时间：2026-08-16 · 状态：只读扫描 → 列出改动范围 → 待协调者确认后实施

## 1. 仓库当前状态（基线）

- 远端 main = `2e8ce99`（v0.4.4），工作区干净，**110 个测试全绿**；
- TraeWork 的 history 改动已由协调者提交推送（`2bb00fa` → `8d8cc8e`），
  **不存在未提交的 TraeWork 改动**，你可以直接修改，无需担心干扰；
- 本轮协调者新增并已推送：`config.load_dsh_credentials()`（自动读 ~/.dsh/.credentials.yaml）、
  `dsh/` 社区安装套件、版本号 0.4.4；
- tag v0.4.4 已推送。

## 2. 审查范围（按你提议）

并发（ThreadPoolExecutor 使用、锁粒度）、错误处理（异常分类与传播）、
MCP/HTTP 协议（JSON-RPC 边界、状态码、输入校验）、打包（pyproject 元数据、wheel 内容）、
文档（与实现一致性）。可参考 GitHub 社区优秀实现，但保持本项目风格。

## 3. 约束（必须遵守）

1. **不改动行为契约**：`run()` 的统一结果结构、HTTP 端点路径与字段、MCP 工具名与
   inputSchema、CLI 参数——这些是 DSH/外部调用方的负载接口，只允许修复 bug 或
   严格兼容的增强；
2. **不破坏兼容性**：运行时保持纯标准库；Python >= 3.10（CI 矩阵 3.10/3.11/3.12）；
   全部 110 个测试必须保持通过（允许新增测试）；
3. **禁区**：`dsh/`（刚发布）、`deploy/`、Docker 相关文件、`.github/workflows/*`（CI/publish 在跑）；
4. **不要提交** `conftest.py` / `_probe*.py` 等调试产物（.gitignore 已覆盖 `_probe*`，
   但 conftest 是本机沙箱 hack，绝不入库）；
5. 不要执行 `git push`；改动完成后写 `AGENT_TASKS/codex_task_quality_done.md`（改动清单 + 测试结果）。

## 4. 协调流程

- 你列出改动范围后，协调者会确认无冲突；
- 实施期间如发现需要动"禁区"文件的问题，先在完成报告里说明，由协调者决定；
- 完成后协调者会：全量测试 → 审查 diff → 版本号递增（0.4.5）→ 提交推送 → tag + Release。
