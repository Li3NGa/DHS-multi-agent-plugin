# 贡献指南

感谢您考虑为 DHS Multi-Agent 项目做出贡献！本文档将帮助您了解如何参与贡献。

## 代码行为准则

参与本项目即表示您同意尊重所有贡献者，保持专业和友善的沟通氛围。

## 如何贡献

### 报告 Bug

请通过 [GitHub Issues](https://github.com/Li3NGa/DHS-multi-agent-plugin/issues) 提交 Bug 报告。好的 Bug 报告应包含：

- **清晰的标题和描述**
- **复现步骤** — 尽可能详细
- **预期行为 vs 实际行为**
- **环境信息** — Node.js/Python 版本、操作系统
- **最小复现示例**（如果可能）

### 功能建议

欢迎提交功能建议！请在 Issue 中说明：

- 您遇到的问题或使用场景
- 您期望的解决方案
- 替代方案（如果有的话）

### 提交代码

1. **Fork 仓库** 并创建您的分支
2. **确保测试通过** — 所有新代码应有对应的测试
3. **遵循代码风格** — 与现有代码保持一致
4. **写清楚提交信息** — 简洁描述变更内容
5. **提交 Pull Request** — 详细说明您的变更和原因

## 开发环境设置

### TypeScript (Native)

```bash
# 安装依赖
pnpm install --frozen-lockfile

# 运行测试
pnpm --dir packages/dsh-multi-agent test

# 类型检查
pnpm --dir packages/dsh-multi-agent typecheck

# 构建
pnpm --dir packages/dsh-multi-agent build
```

### Python

```bash
# 安装开发版本
pip install -e .

# 运行测试
pytest tests/ -q
```

## 代码规范

- TypeScript：遵循 `tsconfig.json` 中的严格模式
- Python：遵循项目现有代码风格
- 添加测试：所有新功能应有对应的单元测试
- 更新文档：如果您的变更影响公共 API，请更新相关文档

## Pull Request 清单

提交 PR 前请确认：

- [ ] 所有测试通过
- [ ] 类型检查无错误
- [ ] 新代码有对应的测试
- [ ] 文档已更新（如需要）
- [ ] 提交信息清晰明了
- [ ] PR 描述清楚说明变更内容和原因

## 社区

- 有问题？开一个 Issue 讨论
- 关注安全更新：请开启 Watch 通知

再次感谢您的贡献！🎉
