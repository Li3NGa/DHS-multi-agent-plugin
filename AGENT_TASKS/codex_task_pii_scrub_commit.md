# Codex Agent 任务书：提交并推送个人信息脱敏修改

> 使用方式：在 Codex 环境中打开本仓库目录，将本文件内容作为任务执行。
> 完成后写完成报告到 `AGENT_TASKS\codex_task_pii_scrub_commit_done.md` 并通知协调者。

## 背景

协调者（Trae）已完成一次个人信息脱敏扫描：工作区 7 个文件中含本机 Windows
用户名的绝对路径已被替换为通用占位路径；同时本仓库 `.git/config` 的 `[user]`
邮箱已改为 `Li3NGa@users.noreply.github.com`（方案 A：不动历史，只保证未来
提交干净）。这些修改当前**尚未提交**，需要你完成提交与推送。

## 任务

1. 先执行 `git status` 确认工作区状态；只允许暂存下列 7 个文件，
   不得包含其他任何文件（本地的 probe / egg-info / pid 等残留一律不动）：

   - `AGENT_TASKS/trae_task_relay.md`
   - `AGENT_TASKS/traework_task_history.md`
   - `deploy/install.ps1`
   - `deploy/README.md`
   - `docs/mcp.md`
   - `docs/usage.md`
   - `dsh/cordis.patch.yml.example`

2. 提交（作者邮箱应已经是 noreply，可用 `git log -1 --format='%ae'` 验证）：

   ```
   git commit -m "chore: scrub machine-specific paths (remove username from docs and deploy scripts)"
   ```

3. 推送：`git push origin main`。

4. 推送完成后，把本任务书与你的完成报告一起补一个 chore 提交并推送
   （与本仓库 AGENT_TASKS 文件的既有提交方式一致）。

## 约束

- 只改上面列出的文件；不重写历史、不 force push、不打 tag；
- 不修改 `.git/config`（user 段已由协调者配置好）；
- 若 `git status` 出现清单之外的被跟踪文件改动，先停下来在完成报告中
  说明情况，不要擅自提交；
- 完成报告包含：实际提交的 commit hash、`git log -1 --format='%an <%ae>'`
  的输出、推送结果。

## 验收标准

- 远端 main 上新增 1 个脱敏提交（+1 个 AGENT_TASKS chore 提交）；
- 新提交作者邮箱为 `Li3NGa@users.noreply.github.com`；
- 提交内容仅含上述 7 个文件的路径清理，无其他文件混入。
