# ADR-0005: HTTP 远程监听默认 fail-closed

- 状态：已采纳
- 日期：2026-09-01
- 关联：ADR-0003、ADR-0004

## 背景

HTTP 适配器默认监听 `127.0.0.1`，因此开发者本地运行可以保持零配置。
但通过 `--host 0.0.0.0`、`--host ::` 或其他非 loopback 地址启动时，服务
此前仍允许无鉴权启动。由于 `/run`、`/register` 等接口具备执行和状态修改能力，
这使“监听范围”与“访问控制”在部署配置错误时脱钩。

## 决策

### 1. Loopback 继续兼容

以下地址视为本地 loopback，可以无 token 运行：

- `localhost`
- IPv4 loopback（例如 `127.0.0.1`）
- IPv6 loopback（`::1`）

其他 hostname 不自动视为本地。原因是 hostname 的 DNS 解析可能发生变化，不能
成为绕过远程认证保护的依据。

### 2. 非 loopback 默认拒绝无认证启动

`build_server()` 与 `serve()` 在绑定服务器之前调用 `validate_bind_security()`。
当 host 为非 loopback、且没有 `token` / `roles` 时，直接抛出 `ValueError`，不创建
HTTP server。

### 3. 提供明确的破例开关

新增 CLI / API 参数 `allow_insecure_remote=False`，以及 CLI：

```text
--allow-insecure-remote
```

只有显式设置该选项，才允许无认证远程监听，并记录 warning。它只用于已经由网络 ACL、
隔离测试网等外层机制保护的可信私有网络，不作为生产公网配置建议。

## 兼容性

- 默认 host `127.0.0.1` 不变。
- 已配置 `--token` / `DS_AGENT_TOKEN` / `--role` / `DS_AGENT_ROLES` 的远程部署不变。
- 仅有“远程监听 + 无认证”的旧部署会从启动成功变为启动失败，这是有意的安全修复。
- `build_server` 新增参数位于现有参数末尾，既有位置参数调用不受影响。

## 验证

R8 增加了 loopback、IPv4/IPv6、hostname、无认证远程拒绝、token/RBAC 远程放行、
以及显式 insecure opt-in 的测试覆盖；完整 CI 继续执行 Python 多版本测试、Native
Runtime、依赖安全扫描。
