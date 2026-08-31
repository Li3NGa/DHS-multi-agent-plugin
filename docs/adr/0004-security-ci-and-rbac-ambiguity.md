# ADR-0004: Security CI 与 RBAC 配置确定性

- 状态：已采纳
- 日期：2026-09-01
- 关联：ADR-0003（HTTP 加固与并发 run 限流）

## 背景

HTTP 适配器已经具备 body 大小限制、Content-Length 校验、Content-Type
约束、RBAC、run 并发门卫和敏感日志脱敏。R7 审计发现两个剩余的工程化缺口：

1. GitHub Actions 默认权限没有被显式收窄，未来 workflow 扩展时容易无意取得超出
   CI 所需范围的 GitHub 权限。
2. Python 与 Native npm 依赖没有独立的漏洞扫描门禁，普通测试通过并不意味着
   依赖供应链状态可接受。
3. RBAC 配置允许同一个 bearer token 被同时分配给不同角色；最终权限取决于
   Python mapping 构造顺序，属于隐式权限漂移。

## 决策

### RBAC

`TokenAuthenticator` 拒绝一个 token 被多个不同角色复用，启动阶段直接报错。
同一 token 必须明确对应一个且仅一个权限级别。

### CI 权限

Python CI 与 Native Runtime CI 显式设置：

```yaml
permissions:
  contents: read
```

并给作业增加有限的 `timeout-minutes`，避免异常情况下 runner 无界占用。

npm Publish workflow 保持独立，并仅请求 `contents: read` + `id-token: write`，用于
Trusted Publishing。

### 依赖安全门禁

新增 `Security Audit` workflow：

- Python：安装 runtime package 后执行 `pip-audit --strict`；
- Native：冻结安装 lockfile 后执行 `pnpm audit --prod --audit-level high`；
- 每周定时运行，同时对依赖相关 PR 触发。

这两个门禁均只读仓库内容，不需要写权限。

## 影响

- 共享 token 的旧 RBAC 配置会从“隐式覆盖”变为启动失败，需要显式修正配置。
- CI 权限更严格，不影响现有测试、构建和发布动作。
- 安全扫描可能因为未来上游依赖出现高危漏洞而主动阻断合并，这是预期行为。

## 后续

公网开放模式的 host-level fail-closed（非 loopback 无 token 时禁止启动）仍属于
独立的 HTTP 入口语义变更，留给下一轮在兼容性范围与嵌入式调用场景核实后处理；
R7 不通过隐式 monkey-patch 改变现有 `build_server` / `serve` 入口行为。
