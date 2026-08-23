# Phase B 迁移映射：dsh-native/ → packages/dsh-multi-agent/

Source of Truth 迁移的唯一权威映射（行为零变化，只移动与改路径）。

## 文件映射

| dsh-native/ | packages/dsh-multi-agent/ | 变化 |
|---|---|---|
| `src/**`（task/graph/dsh/runner/scheduler/index/strategies） | `src/**` | 无（字节不变） |
| `tests/*.test.ts` + `tests/helpers.ts` | `tests/unit/` | 导入 `../src` → `../../src` |
| `smoke/dsh.smoke.spec.ts`（源码级真实 runtime） | `tests/integration/dsh.runtime.spec.ts` | 导入路径调整（真实 DSH runtime、源码级） |
| `smoke/dsh.bundle.spec.ts`（bundle 产物级） | `tests/smoke/dsh.bundle.spec.ts` | `../dist` → `../../dist`、`../src` → `../../src` |
| `smoke/support.ts` | `tests/smoke/support.ts` | 无 |
| （新增） | `tests/smoke/root-entry.smoke.spec.ts` | 真实 harness 加载 **根 dist/index.js**（`dsh plugin add` 的实际入口） |
| `vitest.config.ts` | 同位置 | include → `tests/unit/**` |
| `vitest.smoke.config.ts` | 同位置 | include → `tests/smoke/**` + `tests/integration/**` |
| `tsconfig.json` | 同位置 | include → `["src","tests","vitest.config.ts","vitest.smoke.config.ts"]` |
| `package.json` | 同位置 | +`private:true`；`test:smoke` 改用 pnpm；其余不变（依赖仍 0.1.1-rc.2 线） |
| `pnpm-workspace.yaml` | **删除**（并入根 workspace） | workspace 成员不得自有 workspace 文件；设置合并至根 |
| `pnpm-lock.yaml` | **删除** | 单一根 workspace lockfile |
| `.gitignore` / `README.md` / `cordis.patch.yml.example` | 同位置 | 无 |
| `dist/`（ignored 构建产物） | `dist/` | esbuild 重建 |

## 根发布壳（用户入口不变）

| 项 | 迁移后 | 说明 |
|---|---|---|
| `name` / `main: dist/index.js` / `exports` / `files: [dist]` / `dsh.bundle` manifest / `cordis.patch.yml` | **不变** | `dsh plugin add pnpm` 安装模型逐字保留 |
| `prepare` | `tsc` → `pnpm run build` | build 改为 esbuild 从 `packages/dsh-multi-agent/src/index.ts` 打包出 `dist/index.js`（`@deepseek-ai/*` external，宿主提供） |
| `pnpm-workspace.yaml` | +`packages: ['packages/*']` +合并成员设置 | 根成为 workspace；成员 devDeps 在插件安装流程中随 install 就绪 |
| `dependencies` | 不变（0.1.1-rc.2 线四包） | 宿主/安装环境运行时解析 |
| `typecheck` / `test` | 过渡期仍指向根 src/tests；退役提交后委托给包 | 见下 |

## Root Native（transitional）退役判据

`src/index.ts`、`src/runner.ts`、`tests/plugin.spec.ts`、根 `tsconfig.json`/`vitest.config.ts`
在以下全部确认后由独立 chore 提交删除（快照 tag `dhs-root-native-final` 保底）：

- [ ] 根 `build`/`prepare` 产物来自 packages（esbuild），不含根 src
- [ ] 根 `exports`/`main` 指向的 dist 与根 src 无关
- [ ] runtime（真实 DSH smoke + root-entry smoke）只经 packages 与根 dist
- [ ] 过渡 CI job 只测根 src 自身，迁移后删除
- [ ] 根 `typecheck`/`test` 委托给 packages/dsh-multi-agent

## CI 映射

`dsh-native.yml` → `native-runtime.yml`：从根 workspace 运行
（`pnpm install --frozen-lockfile` → 成员 typecheck/test → 根 build → `test:smoke`
含 bundle/config-agent/root-entry），paths 过滤改为
`packages/dsh-multi-agent/**` + 根发布壳文件。
