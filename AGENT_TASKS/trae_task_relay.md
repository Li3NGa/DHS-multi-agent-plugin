# Trae Agent 任务书：新增 relay（接力迭代）协作策略

> 使用方式：在 Trae IDE 中打开本仓库目录（本仓库的本地克隆路径），
> 用 Agent 模式，将本文件内容作为任务交给 Trae Agent 执行。完成后请通知协调者审查。

## 背景

本仓库是一个 Python 多智能体协同插件（当前版本 0.3.0，src 布局，setuptools 打包）。
核心概念：

- `AgentCoordinator.run(prompt, strategy, **kwargs)`：按策略调度多个 Agent 协作，
  返回统一结果结构 `{"strategy", "prompt", "rounds", "final", "meta"}`；
- 协作策略实现位于 `src/deepseek_multi_agent_plugin/strategies.py`，
  以 `run_<name>(coord, prompt, **opts)` 函数形式存在，并注册到文件底部的 `STRATEGIES` 字典；
- 策略内部用 `_call_agent(agent, message, context, timeout)` 调用 Agent（异常返回 `{"error": ...}`）、
  用 `_record(coord, role, content, agent)` 写入共享记忆、用 `_meta(...)` 生成元信息；
- 现有策略：broadcast、sequential、debate、supervisor、consensus（可参考 `run_sequential` 的写法）；
- 测试在 `tests/` 目录，用 `.venv\Scripts\python.exe -m pytest -q` 运行（当前 71 个测试全部通过）；
- CLI 在 `src/deepseek_multi_agent_plugin/cli.py`，run 子命令的 `--strategy` 参数是硬编码的 choices 列表。

## 任务：实现 relay 策略

`relay`（接力迭代）：Agent 按顺序轮流打磨同一份草稿，后一位看到前一位的产出，
所有 Agent 跑完一遍算一轮；支持多轮和提前收敛。

### 行为规格

1. 函数签名：`run_relay(coord, prompt, rounds=2, order=None, timeout=None)`。
2. 初始草稿 = 任务提示词本身。
3. 每轮内：按 `order`（默认注册顺序）依次调用每个 Agent，传入消息格式：
   「原始任务 + 当前草稿 + 要求：请改进下面这份草稿，只输出改进后的完整草稿」；
   每个 Agent 的输出成为新草稿，并记录 `{"step": i, "agent": 名字, "response": 新草稿}`。
4. 每轮结束后检查是否收敛：若该轮结束时草稿与轮初完全相同，立即提前结束（记录 `"converged": true`）；
   连续两轮无变化也提前结束。
5. 单轮内某个 Agent 出错（`{"error": ...}`）：跳过该 Agent，草稿保持不变并记录错误。
6. `final` = 最终草稿。
7. `rounds` 记录结构示例：
   `{"round": 1, "kind": "relay", "steps": [...], "converged": false}`。
8. 注册到 `STRATEGIES` 字典（`"relay": run_relay`），保证 `coord.run(prompt, strategy="relay")` 可用；
   最少 2 个 Agent，否则抛 ValueError（与 debate 一致）。

### 需要修改的文件

1. `src/deepseek_multi_agent_plugin/strategies.py`：实现 `run_relay` 并注册；
2. `src/deepseek_multi_agent_plugin/cli.py`：`--strategy` 的 choices 增加 `"relay"`；
3. 新增 `tests/test_relay.py`：至少覆盖
   - 正常接力：3 个 mock Agent 依次加工草稿，断言每一步的输出进入了下一棒的输入、final 正确；
   - 收敛提前结束：Agent 不改动草稿时，轮数提前结束且 `converged` 为 true；
   - 错误跳过：某个 Agent 抛异常时草稿不丢失、其他 Agent 继续；
   - 少于 2 个 Agent 抛 ValueError；
   - `order` 参数生效；
4. 文档：`docs/strategies.md` 增加 relay 章节（流程/参数/示例/适用场景）、
   `docs/api_reference.md` 第 5 节增加签名、`docs/usage.md` 第 4 节表格加一行、
   `README.md` 的协作策略表格加一行；
5. `example_config.yaml` 不需要改动。

### 验收标准

- 用 `.venv\Scripts\python.exe -m pytest -q` 运行，全部测试（含新增）通过；
- 用 mock Agent 跑一次完整接力：
  `.venv\Scripts\python.exe -m deepseek_multi_agent_plugin.cli run --agents 初稿员,润色员,审校员 --strategy relay --rounds 2 --prompt "写一段产品介绍"` 正常输出；
- 不破坏现有 71 个测试与任何既有策略行为。

### 约束

- 不要执行 `git push`；
- 不要改动 Docker 部署相关文件（Dockerfile、docker-compose.yml、.dockerignore、docs/deployment.md、deploy/），
  那部分正由另一位 agent 并行开发；
- 不要改动 README 中与 Docker 部署有关的章节（只加策略表格那一行）；
- 保持与现有代码风格一致（中文注释与文档、类型标注、标准库实现）；
- 完成后在 Trae 对话里总结改动文件清单与测试结果。
