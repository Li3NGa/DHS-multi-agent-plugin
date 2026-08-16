# TraeWork Agent 任务书：运行结果持久化 + 历史查询（Run History）

> 使用方式：在 TRAE SOLO CN（TraeWork）中打开本仓库目录
> （C:\Users\admin\deepseek-multi-agent-plugin），进入工作模式，将本文件内容
> 作为任务交给 TraeWork Agent 执行。完成后通知协调者审查。

## 背景

本仓库是 Python 多智能体协同插件（v0.4.2，97 个测试全绿）。目前每次协作任务（run）的
完整结果只存在于当次响应中，服务重启后即丢失。本任务为插件增加**运行历史持久化**与
**历史查询**能力。

关键事实：
- HTTP 适配服务：src/deepseek_multi_agent_plugin/adapter_server.py（ThreadingHTTPServer +
  DeepseekAdapter，端点 /health /agents /run /register，Bearer 鉴权）；
- MCP 服务器：src/deepseek_multi_agent_plugin/mcp_server.py（tools: run/agents/register/status）；
- DeepseekAdapter.handle_harness_event(event) 处理 run/agents/status/register 四类事件；
- 配置：src/deepseek_multi_agent_plugin/config.py（load_config/build_coordinator）；
- 测试在 tests/，用 .venv\Scripts\python.exe -m pytest -q 运行（当前 97 个全部通过）；
- 文档：docs/http_api.md、docs/mcp.md、docs/usage.md、docs/api_reference.md；
- 版本号：pyproject.toml 与 src/.../__init__.py 两处（当前均为 0.4.2）。

## 任务：实现 RunHistory 持久化与查询

### 1. 新增模块 src/deepseek_multi_agent_plugin/history.py

- 类 RunHistory：线程安全地以 JSONL 追加方式把 run 记录写入文件；
- 构造：RunHistory(path: str)（文件不存在时自动创建父目录）；
- 方法：
  - append(record: dict) -> dict：补充 timestamp（ISO 8601 本地时间）与 index（自增序号），
    写入一行 JSON 并返回记录；
  - recent(limit: int = 20) -> list[dict]：读取最近 limit 条（倒序，最新在前）；
  - clear() -> None：清空文件；
  - __len__ -> int：记录条数；
- 记录内容由调用方决定，建议字段：strategy、prompt、final、rounds 数量、session_id、elapsed_seconds。

### 2. DeepseekAdapter 集成（coordinator.py）

- 构造参数增加 history: Optional[RunHistory] = None；
- run 事件成功执行后，把结果摘要 append 进 history（若提供）；run 失败（error）不记录；
- 新增事件类型 "history"：
  - 请求 {"type": "history", "limit": 10, "session_id": "可选"}；
  - 响应 {"records": [...]}（未启用 history 时返回 {"records": [], "enabled": false}）。

### 3. HTTP 端点（adapter_server.py）

- 启动参数 --history FILE（同时支持环境变量 DS_HISTORY_FILE，缺省不启用持久化）；
- 启用后：GET /history?limit=N 返回最近 N 条记录；
- 每次 POST /run 成功后自动落盘；
- /health 在启用 history 时附加 "history": "on" 与记录条数。

### 4. MCP 工具（mcp_server.py）

- 启动参数 --history FILE；
- _TOOLS 增加 "history"：inputSchema {"limit": {"type": "integer"}}，
  返回 {"records": [...]}；tools/list 保持有序输出；
- 描述写中文。

### 5. 测试（tests/test_history.py）

至少覆盖：
- RunHistory 追加/读取/条数/清空（tmp_path）；
- 并发追加不丢记录（多线程 append 后 len 正确）；
- adapter 记录与 history 事件（未启用时 enabled=false；启用后能查到 run 记录）；
- HTTP：启用 --history 后 GET /history 返回记录、/run 后条数增加、未启用时 /history 返回 enabled=false；
- MCP：tools/list 含 history、tools/call history 返回 records。

### 6. 文档与版本

- docs/http_api.md：/history 端点、--history/DS_HISTORY_FILE 参数表；
- docs/mcp.md：history 工具一行；
- docs/api_reference.md：RunHistory 类与 DeepseekAdapter 新参数、history 事件；
- docs/usage.md：第 6 节 Python API 加 RunHistory 用法示例；
- 版本号两处同步 0.4.2 → 0.4.3。

### 7. 验收标准

- .venv\Scripts\python.exe -m pytest -q 全部通过（97 + 新增）；
- 手工演示：
  a) .venv\Scripts\python.exe -m deepseek_multi_agent_plugin.adapter_server --demo --port 8123 --history $env:TEMP\ds_runs.jsonl，
     执行一次 /run 后 GET /history 能看到记录；
  b) .venv\Scripts\python.exe -m deepseek_multi_agent_plugin.mcp_server --demo --history $env:TEMP\ds_runs2.jsonl，
     stdio 冒烟 tools/call run 后 tools/call history 返回记录。

### 8. 约束

- 不要执行 git push；
- 不要改动 Docker 相关文件（Dockerfile/docker-compose.yml/.dockerignore/docs/deployment.md）与 deploy/ 目录；
- 不要改动 strategies.py 的策略逻辑（可以 import 但不许改行为）；
- 保持纯标准库实现、中文注释与文档；
- 完成后在 AGENT_TASKS/ 写完成报告（traework_task_history_done.md），并用中文总结。
