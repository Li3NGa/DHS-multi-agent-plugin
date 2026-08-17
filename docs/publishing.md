# 发布指南（Publishing Guide）

本文档说明如何把 `deepseek-multi-agent-plugin` 发布到 PyPI，并把构建产物
附加到 GitHub Release。发布成功后，用户可以直接
`pip install deepseek-multi-agent-plugin`，也可以从 GitHub Release 下载
wheel / sdist。

> ✅ 当前状态：**v1.0.0 为当前主干版本**（2026-08-17）；v0.4.8 起已发布到 PyPI。
> 安装：`pip install deepseek-multi-agent-plugin`。
> 后续发布流程：推送 `v*` tag 即自动构建、上传 PyPI 并附加 GitHub Release。
> 版本号规范：只需修改 `src/deepseek_multi_agent_plugin/__init__.py` 中的
> `__version__`（单一来源，`pyproject.toml` 动态引用）。

---

## 1. 发布流程总览

仓库使用 Git tag 触发发布：打 tag 后 GitHub Actions 自动完成构建、校验与双通道分发。

| 步骤 | 操作 | 触发结果 |
| --- | --- | --- |
| 1 | 更新版本号并提交（改 `__init__.py` 的 `__version__`，见第 4 节版本号规范） | 代码进入仓库 |
| 2 | 打标签 `git tag v1.0.0` 并推送 `git push origin v1.0.0` | 触发 `publish.yml` |
| 3 | CI 构建 wheel + sdist，运行 `twine check` | job 1（build-and-publish） |
| 4 | 发布到 PyPI | job 1 上传 `deepseek-multi-agent-plugin-X.Y.Z` |
| 5 | 把 `dist/*.whl`、`dist/*.tar.gz` 附加到 GitHub Release | job 2（release-upload） |

> 说明：GitHub Release 仍由人工创建；`release-upload` 会把构建产物附加到
> 同名 tag 对应的 Release，若 Release 尚未创建会自动创建一个。

---

## 2. 配置 PYPI_API_TOKEN

发布 job 通过 `pypa/gh-action-pypi-publish@release/v1` 上传到 PyPI，使用
PyPI API token 认证。配置分为两步：

### 2.1 在 PyPI 官网申请 API token

1. 登录 [PyPI](https://pypi.org)；
2. 进入 `Account settings` → `API tokens`；
3. 点击 `Add API token`：
   - `Token name`：建议写 `github-actions` 或 `deepseek-multi-agent-plugin-publish`；
   - `Scope`：选择 `Project: deepseek-multi-agent-plugin`（仅限本项目），
     或 `Entire account`；
4. 点击 `Add token` 后复制生成的 token，形如：

   ```
   pypi-AgEIcHlwaS5vcmcCJDEwZ...（示例占位，请勿使用）
   ```

> ⚠️ token 只在创建时显示一次，请立即保存到密码管理器；不要把真实 token
> 写入仓库、文档或提交记录。

### 2.2 在 GitHub 仓库配置 Secret

1. 打开仓库页面，进入 `Settings` → `Secrets and variables` → `Actions`；
2. 点击 `New repository secret`；
3. `Name` 填写 `PYPI_API_TOKEN`（必须与工作流中
   `secrets.PYPI_API_TOKEN` 完全一致）；
4. `Secret` 粘贴 2.1 步复制的 token；
5. 点击 `Add secret` 保存。

配置完成后，下次推送 `v*` tag 时发布流水线即可通过认证。若尚未配置，
job 1 的 `Publish to PyPI` 步骤会失败——这是预期行为（避免误发布），
此时请配置 Secret 后重新触发，或改用下面的本地手动发布。

---

## 3. 本地手动发布

不需要 CI 时，可以在本机完成同样的构建与上传：

```bash
# 安装构建与上传工具（若尚未安装）
python -m pip install build twine

# 1. 构建 wheel + sdist 到 dist/
python -m build

# 2. 校验产物（README 渲染、元数据、文件完整性）
twine check dist/*

# 3. 上传到 PyPI（使用 API token，用户名固定为 __token__）
twine upload dist/*
```

也可以显式传入凭据：

```bash
twine upload -u __token__ -p "pypi-..." dist/*
```

建议通过环境变量或 `~/.pypirc` 保存凭据，避免 token 出现在 shell 历史中：

```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD="pypi-..."
twine upload dist/*
```

> 注意：上传前请先确认 `dist/` 中只有当前版本产物，旧版本残留文件
> 会被一起上传并触发 409 错误。

---

## 4. 版本号规范

版本号自 v1.0.0 起为**单一来源**，只需改一处：

| 文件 | 位置 | 说明 |
| --- | --- | --- |
| `src/deepseek_multi_agent_plugin/__init__.py` | `__version__` | 唯一需要修改的地方 |
| `pyproject.toml` | `[tool.setuptools.dynamic]` | `version = { attr = "deepseek_multi_agent_plugin.__version__" }`，自动引用，无需改动 |

tag 命名规则：

- 使用 `vX.Y.Z` 格式（如 `v1.0.0`），`publish.yml` 由 `v*` 标签触发；
- tag 应打在版本号已同步更新的提交上；
- PyPI 不允许重复上传同一版本，发布过的版本不能覆盖修改，只能发布新版本。

发布新版本的推荐顺序：

```bash
# 1. 修改 __init__.py 中的 __version__（单一来源）
# 2. 提交改动
git add src/deepseek_multi_agent_plugin/__init__.py CHANGELOG.md
git commit -m "chore: bump version to X.Y.Z"

# 3. 打 tag 并推送（触发 CI 发布）
git tag vX.Y.Z
git push origin vX.Y.Z
```

---

## 5. 常见问题

### 5.1 twine check 失败

`twine check` 会校验 README 渲染与包元数据，失败时输出 `ERROR` / `WARNING`：

- 检查 `pyproject.toml` 的 `readme` 路径与格式是否正确；
- README 中的 Markdown 语法需在 PyPI 上可正常渲染（PyPI 使用较严格的
  CommonMark / reStructuredText 解析，注意表格、代码块等写法）；
- 修复后重新执行 `python -m build`，再 `twine check dist/*`。

### 5.2 409 File already exists

说明该版本号已经上传过 PyPI。PyPI 不允许覆盖或删除后重传同名版本：

- 递增 `__init__.py` 中的 `__version__`（单一来源，如 `1.0.1`）；
- 重新打新 tag（如 `v1.0.1`）并推送。

> 本地手动发布时，先清理 `dist/` 中的旧版本产物，避免把旧文件一起上传。

### 5.3 凭据失效（401 / 403）

发布步骤报 `401 Invalid or non-existent authentication information` 或
`403 Forbidden` 时：

- 到 PyPI `Account settings` → `API tokens` 检查 token 是否存在、未过期、
  作用域是否包含 `deepseek-multi-agent-plugin`；
- 重新生成 token 后，到 GitHub `Settings` → `Secrets and variables` →
  `Actions` 更新 `PYPI_API_TOKEN`；
- 确认 Secret 名称与工作流中的 `secrets.PYPI_API_TOKEN` 完全一致；
- 本地发布时确认使用的是 `__token__` 用户名 + API token，而不是 PyPI 登录密码。

---

## 6. 相关文档

- [详细使用说明](usage.md) — 安装与四种使用方式（Python API / CLI / HTTP / MCP）
- [部署指南](deployment.md) — Windows / Docker / systemd 部署
- [README](../README.md) — 项目总览
