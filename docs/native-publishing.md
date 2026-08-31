# Native npm 发布指南

本文档专门描述 Native Runtime 包 `dhs-multi-agent` 的发布流程。
Python 包 `deepseek-multi-agent-plugin` 继续使用现有的 PyPI 发布流程，两条发布链彼此隔离。

## 当前发布契约

- npm package：`dhs-multi-agent`
- Native package version：以根目录 `package.json` 为唯一版本来源
- Node.js：`>=22.14.0`
- 发布标签：`npm-vX.Y.Z`
- 标签必须与 `package.json.version` 完全一致
- 发布工作流：`.github/workflows/npm-publish.yml`
- 发布前必须通过 Native Runtime CI
- **R6 只负责把发布链工程化到可发布状态，不自动创建版本 tag，不绕过 npm 侧 Trusted Publishing 配置。**

## 产物契约

npm tarball 必须包含：

- `dist/index.js`：发布入口
- `dist/types/index.d.ts`：TypeScript 公共类型声明
- `cordis.patch.yml`：DSH bundle 装配所需 patch
- `package.json`：名称、版本、exports、repository 等元数据

Native CI 的 clean consumer smoke 会从 `npm pack` 生成的真实 tarball 安装，检查以上文件，并分别验证运行时 import 与 TypeScript 类型解析。

## 首次启用 Trusted Publishing

npm 官方建议使用 GitHub Actions Trusted Publishing（OIDC），避免把长期 npm token 放进仓库 Secrets。Trusted Publishing 要求发布 workflow 拥有 `id-token: write` 权限，并且 npm 侧配置的 repository、workflow filename 必须与实际发布工作流精确一致。

在 npm package 设置中，将 GitHub Actions Trusted Publisher 配置为：

- Owner：`Li3NGa`
- Repository：`DHS-multi-agent-plugin`
- Workflow filename：`npm-publish.yml`
- Allowed action：`npm publish`

注意：npm 官方当前文档要求 Trusted Publishing 使用 Node.js 22.14.0+ / npm CLI 11.5.1+。本工作流固定使用 Node 24，以满足该要求并避免老版本运行时差异。

## 发布步骤

```bash
# 1. 修改 package.json version，例如 0.2.0
# 2. 提交代码并确保 main CI 全绿
# 3. 创建并推送严格匹配的 tag

git tag npm-v0.2.0
git push origin npm-v0.2.0
```

工作流会依次执行：source-of-truth guard → TypeScript typecheck → Native unit tests → distributable build → tag/version 校验 → `npm pack --dry-run` → `npm publish`。

## 回滚原则

npm 已发布版本不可覆盖。发现问题时不要重用同一版本号，必须递增补丁/次版本并重新发布。例如 `0.2.0` 出问题后使用 `0.2.1`。

GitHub Release、npm 发布与 Python PyPI 发布不要共享同一个“万能 tag”规则；Native 使用 `npm-v*`，避免误触发 Python 发布链。
