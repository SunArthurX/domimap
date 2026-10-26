# mcp-write-gate — MCP 写能力显式启用，转达判定降为非权威来源

日期：2026-10-26。依据 docs/superpowers/plans/2026-10-26-drift-analysis-and-priorities.md §2.5 与 Task 2。

## 关联需求与案例

- R08（信任边界：入口不扩权限）；R15（反馈来源分列，AI/代理不覆盖人源）。
- AC-R08-02（"非授权请求不写入，不扩大权限"——MCP 默认不公布、不执行写工具）；AC-R15-02（"来源分列不合并；AI 不覆盖人源"——经 MCP 转达的判定不进权威口径）。

## 问题

roadmap.md:146 要求"MCP 写能力明确启用、与只读分开，服务端校验参数和目标范围"。drift-correction-c6 加入的 `kg_feedback` 无条件进入 `TOOLS` 并在 `tools/list` 广播（mcp.py:41-57, 301-302）；`serve()`/`Server()` 无开关；`:291` 注释仍称 "read-only"；handler 硬编码 `source="user_feedback"`（:217），而该来源在 `feedback.AUTHORITATIVE_SOURCES`（feedback.py:26）——任何 MCP 客户端（LLM Agent）可写入"用户判定"并直接主导命中率/覆盖率/诊断队列统计。

## 预期用户结果

- `domimap serve -g graph.json`（默认）：`tools/list` 恰 6 个只读工具；调用 `kg_feedback` 返回 `isError=true` 且文案含 `write_disabled`（不是静默成功，也不是 tool_failed）。
- `domimap serve -g graph.json --enable-write`：`tools/list` 7 个；`kg_feedback` 可用，落库 `source="agent_relay"`，响应 JSON 附 `"source":"agent_relay"`。
- `agent_relay` ∈ `SOURCE_VALUES`、∉ `AUTHORITATIVE_SOURCES`：不改变 `effective()`、hit_rate、覆盖率、诊断问题队列的任何口径；人工确认仍经 UI/CLI 以 `user_feedback` 提交。
- `schema.json` 新增 `mcp_write_tools: ["kg_feedback"]`，契约测试绑定 `mcp.WRITE_TOOLS` 与 `visible_tools(False)`。

## 契约

- `mcp.WRITE_TOOLS: frozenset[str]`；`mcp.visible_tools(enable_write) -> list[dict]`；`Server(graph_path, enable_write=False)`；`serve(graph_path, enable_write=False)`；CLI `serve --enable-write`。
- 参数校验仍走同源 `_validate_arguments`（schema 不变）；目标范围仍是图旁 `queries.db`。

## 设计选择

- 门控放在 `Server.call()` 最前（在参数校验前），使"未启用"与"非法参数"可区分；`tools/list` 用 `visible_tools` 过滤，避免客户端看到不可用工具。
- 不新增来源确认流程（更大改动属 T12 知识层写入口）；先保证"代理判定不冒充人源"这一不变量。

## Given/When/Then

- 正例：Given 默认服务 / When tools/list / Then 6 工具无 kg_feedback；Given `--enable-write` / When 提交 hit / Then feedback.source=agent_relay，stats 的 hit_rate 不变（无权威反馈）。
- 负例：默认服务调用 kg_feedback → isError + write_disabled；`relevance` 枚举外 → invalid params（原有）；超大帧后 tools/list 仍为 6（test_production_boundaries 调整断言 7→6，原意"错误有界后续可用"不变）。

## 文件与有序任务

1. tests/test_mcp_write_gate.py（5 项，先红）。
2. mcp.py：WRITE_TOOLS/visible_tools/Server.enable_write/call 门控/source=agent_relay/响应附 source/注释与描述；feedback.py SOURCE_VALUES；__main__.py serve --enable-write 与 help；ui.py 文案。
3. schema.json `mcp_write_tools` + tests/test_schema.py 契约；test_feedback/test_production_boundaries 对齐新契约。
4. 文档：production-readiness.md:39、README 两处。

## 验证 / 回滚

见 manifest。

## 遗留

- `docs/clients.md` 的四客户端登记命令未加 `--enable-write`（默认只读是正确的客户端默认）；需要反馈回路的客户端自行加参数。
