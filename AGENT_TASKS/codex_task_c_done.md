# cli agent 桥接完成报告（by Codex Agent）

> 任务：新增 `kind="cli"` 外部命令行 agent，使其可参与 broadcast/sequential/debate/supervisor/consensus/relay 等协作策略
> 完成时间：2026-08-16 · 状态：待协调者审查

## 改动文件清单

| 文件 | 改动 |
| --- | --- |
| `src/deepseek_multi_agent_plugin/agents.py` | `AgentFactory` 新增 `kind="cli"`：kwargs 为 `command`（必填）、`args`（默认 `[]`）、`timeout`（默认 300 秒）、`cwd`、`encoding`（默认 utf-8）；handler 用 `subprocess.run([command, *args, str(message)], capture_output=True, timeout=..., cwd=..., encoding=...)` 执行；退出码 0 且 stdout 非空返回 `stdout.strip()`，stdout 为空返回 `stderr.strip()`，非 0 抛 `RuntimeError(f"cli agent {name} exited {code}: {stderr}")`；`TimeoutExpired` 抛含超时秒数的 `RuntimeError`；`FileNotFoundError/OSError` 在 handler 调用时抛 `RuntimeError`（创建时不校验）；未知 kind 错误信息补充 `cli` |
| `tests/test_cli_agent.py` | 新增 9 个测试（全部使用 `sys.executable` + `python -c` 假命令，不依赖本机 codex）：正常回显 / args 生效 / 非零退出码 / 超时 / 命令不存在 / stdout 为空回退 stderr / cwd 生效 / from_config 透传 / 与 mock agent 一起跑 broadcast 集成 |
| `docs/usage.md` | 3.2 节 agent 字段表：kind 列表加 `cli`，`timeout` 行补充 cli 默认 300 秒，新增 `command`/`args`/`cwd`/`encoding` 行；8.2 节后新增「8.3 外部 agent CLI 桥接（kind: cli）」codex exec 配置示例，原 8.3/8.4 顺延为 8.4/8.5 |
| `docs/api_reference.md` | AgentFactory kind 表新增 `cli` 行及 kwargs 说明 |
| `README.md` | Agent 定义表格新增 `cli` 行；特性与简介更新为「七种后端」，并补充外部 CLI 命令 |

未改动：`strategies.py`（relay 刚合入，保持不动）、`deploy/` 与 Docker 相关文件、`config.py`（`from_config` 已透传 kwargs，无需改代码）。

## 测试结果

- 新增测试：`.venv/Scripts/python.exe -m pytest -q tests/test_cli_agent.py` → **9 passed**
- 全量回归：`.venv/Scripts/python.exe -m pytest -q` → **97 passed**（原 88 + 新增 9）

## 验收演示

1. 字面验收命令（CLI 现状说明）：`run --agents mock,cli --strategy broadcast --rounds 1 --prompt "hello"`
   `--agents` 参数当前只支持按名字创建 mock agent，不支持指定 `kind`，因此按任务约定未改 CLI；
2. 真实 cli 桥接演示：用临时 YAML 配置（`--config`）注册 `mock_agent` + 一个以
   `python -c` 为假命令的 `cli_agent`，跑 `broadcast`，两路响应均出现在结果中；
3. 真实 codex 接入路径：文档中的 `command: .../codex.exe` + `args: [exec, --skip-git-repo-check]`
   配置经 `build_coordinator` 直接可用，测试未依赖本机 codex。
