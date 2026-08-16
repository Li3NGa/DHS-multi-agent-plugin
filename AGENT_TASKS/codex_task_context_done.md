# Codex 任务完成报告：上下文压缩与效率优化（v0.5.0）

> 任务批次：上下文压缩与效率优化；版本 0.4.8 -> 0.5.0；2026-08-16。

## 一、改动清单

### 新模块 src/deepseek_multi_agent_plugin/context.py

- `ContextPolicy` dataclass：`window`（历史窗口，保留最近 N 条）、
  `max_chars`（逐条截断，保留前 N 字符 + `…`）、
  `hide_own_statements`（辩论中隐藏己方旧发言）；附带 `from_dict` 支持
  配置键 `window` / `max_chars` / `hide_own`（兼容全名 `hide_own_statements`）。
- `build_context(prompt, messages, policy, agent_name=None)`：
  原始 prompt 永远作为首条 user 消息保留、绝不截断/不被窗口丢弃；历史首条若与
  prompt 相同则去重；`window` 只作用于历史；`max_chars` 对每条历史内容截断
  （说话人前缀不计入长度）；`hide_own_statements` 按消息 `agent` 字段过滤；
  assistant 消息带说话人前缀 `[agent名]: `，与 `to_chat(with_speaker=True)` 一致。
- `truncate(text, max_chars)` 工具函数（策略级瘦身共用）。

### agents.py

- 新增 `ResponseCache`：线程安全内存 LRU（`OrderedDict` + `Lock`，默认
  maxsize=128，超出淘汰最久未使用条目）。
- `chat_completion` 新增 `cache` 参数：key =
  `sha256(json.dumps((base_url, model, messages, temperature, max_tokens,
  response_format)))`；命中直接返回缓存内容（不打 HTTP），`return_usage=True`
  时 usage 标记 `{"cache_hit": true}`（token 计数归零）；未命中成功后才写缓存。
- `Agent` 新增 `cache: bool=False`（启用时自带 `ResponseCache`）与
  `cache_hits` 计数器；命中时只累计 `cache_hits`，不重复累计 usage；
  `describe()` 增加 `cache` / `cache_hits` 字段（纯增量）。
- `AgentFactory.create_agent` / `from_config` 透传 `cache`；
  mock/echo/http/cli/custom 分支不传 cache，天然不参与缓存。
- `retries` 本已可配置（Agent 构造参数 / factory kwargs / 配置 dict 的
  `"retries"` 字段，默认 2），本次补测试确认行为不变。

### coordinator.py / config.py

- `AgentCoordinator` 新增 `context_policy: Optional[ContextPolicy]=None` 与
  `cache: bool=False` 构造参数；`run()` 额外消费 `context`（ContextPolicy 或
  dict）与 `cache` 两个运行级开关（透传 DeepseekAdapter 事件）。
- `_apply_cache(enabled)`：为已注册的 LLM agent 打开/关闭响应缓存。
- `build_coordinator` 从 `coordinator.context`（dict）构建 ContextPolicy，
  从 `coordinator.cache` 构建协调器缓存。
- `DeepseekAdapter` run 事件透传可选字段 `"context": {...}` 与 `"cache": bool`。

### strategies.py

- `_meta`：`meta["usage"]` 升级为
  `{"total": {prompt/completion/total_tokens}, "agents": {agent名: {...}},
  "cache_hits": N}`；为满足验收（demo 的 JSON 必须含 `meta.usage`），usage
  键现在恒存在（零值填充）。
- `_parallel` 新增可选 `contexts={agent名: 消息列表}` 映射，支持按 agent 定制
  context（debate 使用），共享 context 行为不变。
- 各策略瘦身点（全部仅在 `coord.context_policy.max_chars` 配置时生效，
  **final 结论永不截断**）：
  a) broadcast：`rounds>1` 时回喂消息 `truncate(prompt + 汇总, max_chars)`，
     prompt 前缀保留；最后一轮输出不做截断；
  b) sequential：传给下一棒的 transcript 截断（prompt 前缀保留）；
  c) debate：每轮 `build_context(memory 历史, policy, agent_name=辩手名)` 生成
     每位辩手定制 context；裁判输入按 max_chars 截断；
  d) supervisor：report 步骤的工人结果汇总按 max_chars 截断；
  e) consensus：投票候选 ballot 按 max_chars 截断；
  f) relay：传给下一棒的草稿消息按 max_chars 截断。
- 无 policy 时各策略路径与旧版完全一致（走原有 `to_chat(with_speaker=True)`
  与未截断回喂逻辑）。

### cli.py

- run 子命令新增 `--context-window N`、`--context-max-chars N`（组合成
  ContextPolicy 传给 run）、`--cache`、`--usage`。
- `--usage`：非 JSON 模式在 `== FINAL ==` 之后输出 `== USAGE ==` 摘要
  （total/agents/cache_hits）；JSON 模式 `meta.usage` 直接包含在结果中。

### 版本与文档

- `pyproject.toml` 与 `__init__.py`：0.4.8 -> 0.5.0（两处）。
- `example_config.yaml`：coordinator 增加 `context`（window/max_chars/hide_own
  注释示例）与 `cache` 示例。
- `README.md`：特性区增加「上下文压缩 / 响应缓存 / Token 计量」一行。
- `docs/usage.md`：新增 3.4 节「上下文压缩与效率开关」（ContextPolicy 字段表、
  各策略瘦身点表、CLI 开关示例、缓存说明）。
- `docs/api_reference.md`：补 ContextPolicy / ResponseCache 章节、Agent /
  AgentFactory / AgentCoordinator / chat_completion / DeepseekAdapter /
  build_coordinator 的新参数与 meta.usage 新形状。

## 二、被调整的既有断言列表

仅 1 处既有断言因任务 4 的 usage 汇总形状升级而调整（任务允许并明确要求说明）：

- `tests/test_enhancements.py::test_run_meta_includes_usage`
  - 原断言：`result["meta"]["usage"]["m1"]["total_tokens"] == 10`
  - 新断言：`result["meta"]["usage"]["agents"]["m1"]["total_tokens"] == 10`，
    并补充 `total` 汇总与 `cache_hits == 0` 断言。

其余 130 个既有断言全部未改动。

## 三、新增测试（42 个）

- `tests/test_context.py`（13 个）：truncate、ContextPolicy.from_dict、
  build_context 的 prompt 首位/不截断、window、hide_own、去重、无策略透传。
- `tests/test_cache.py`（11 个）：ResponseCache LRU 淘汰/容量下限/清空、
  chat_completion 命中不打 HTTP、key 区分消息、无缓存不命中、Agent.cache
  命中计数、工厂透传、mock 不参与缓存、retries 可配置。
- `tests/test_context_strategies.py`（15 个）：broadcast 回喂截断/无策略不变、
  sequential transcript 截断、debate 每辩手定制 context + hide_own + 裁判输入
  截断、supervisor 汇总截断、consensus ballot 截断、relay 草稿截断、
  meta.usage 零值填充与汇总、build_coordinator 解析 context/cache、
  DeepseekAdapter 事件透传、coordinator.run context 覆盖、CLI 开关与
  `--usage` 输出位置。
- `tests/test_enhancements.py`：1 个既有断言调整（见上）。

## 四、测试结果

```
173 passed in 13.95s
```

- 旧测试 131 个全部通过（其中 1 个断言按任务 4 升级形状）；
- 新增测试 42 个全部通过。

## 五、手工演示验收

```bash
.venv/Scripts/python.exe -m deepseek_multi_agent_plugin.cli run --demo \
  --context-window 2 --context-max-chars 50 --usage --json --prompt hello
```

输出 JSON 的 `meta` 含：

```json
"usage": {
  "total": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
  "agents": {},
  "cache_hits": 0
}
```

非 JSON 模式 `--usage` 在 `== FINAL ==` 后输出 `== USAGE ==` 摘要。

## 六、约束确认

- 未执行 git push；
- 未改动 dsh/、deploy/、Docker 文件、.github/workflows/*（相关目录在任务开始前
  已有他人未提交改动，本次未触碰）；
- 保持纯标准库（hashlib / collections.OrderedDict / dataclasses / threading），
  Python >= 3.10；
- 本报告落盘后立即冻结一切仓库写入。
