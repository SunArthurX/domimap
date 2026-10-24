# schema-command：机器可读图谱 schema（`domimap schema`）与 README 生产级呈现

- 关联：R11（开源与分发交付，AC-R11-01：净化源码与可分发产物）；R13（AC-R13-01 任务纪律）。
- 来源：用户 2026-10-24 目标——逐项优化直至推送远程；evolution.md E5 首项。

## 正例 / 负例

- 正例：`domimap schema` 输出合法 JSON（节点/边类型、id 前缀、置信度与 prov 域语义、6 个 MCP 工具、4 道拒答门、证据格式）；`tests/test_schema.py` 用真实构建的夹具图反向校验——图中出现的一切 kind/conf/prov 必须 ⊆ schema 声明（防漂移），MCP 工具与 `mcp.TOOLS` 一致，id 前缀一致。
- 正例：README 新增真实运行的 Web UI 截图（docs/assets/domimap-ui.png，Playwright 对本机 UI 实拍）与 schema 章节；docs/knowledge-graph.md 边表修正为 READS/WRITES/MAPS_TO 三种真实边。
- 负例：schema 声明之外新增节点/边 kind 或 prov 域而不更新 schema.json → 契约测试必须失败（本任务开发中即抓到两处真实漂移：READS/WRITES 边、seed/vote prov 域）。

## 实施

1. `domimap/schema.json`：schema_version 1 的机器可读图谱 schema（与 docs/knowledge-graph.md 同步维护，契约测试保证一致）。
2. `domimap/__main__.py`：`schema` 子命令输出该 JSON；pyproject package-data 收录 schema.json（wheel 分发）。
3. `tests/test_schema.py`：6 个契约（必备段落/实际 kind 全声明/置信度与 prov 域覆盖/工具一致/CLI 输出合法 JSON/id 前缀一致）。
4. 文档：knowledge-graph.md §2 边表与 §7 更新；README 截图 + schema 章节；CHANGELOG 0.5.0 补记。

## 验证与回退

- `python3 -B -m unittest tests.test_schema`；`python3 -m domimap schema | python3 -m json.tool`；refresh_evidence 后 `make verify`；新克隆（工作树快照）`make ci`；install_check 冒烟（wheel 含 schema.json）。
- 回退：revert 本提交（schema.json/命令/测试为独立新增，无行为耦合）。
