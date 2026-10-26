# app-service — 公共应用服务：三入口同参、同错、同预算、同热重载

日期：2026-10-26。依据 docs/superpowers/plans/2026-10-26-drift-analysis-and-priorities.md Task 8；production-readiness P1 第一项。

## 关联需求与案例

- product#6（查询语义/范围/新鲜度/错误状态三入口一致；工作与输出预算分别有界）、workflow §6（UI/MCP 不绕开公共服务）。
- AC-R04-02（预算在遍历中执行、partial 可见——此前只有 MCP）；AC-F2-01（UI 与 MCP 主候选同源同序、同参）。

## 问题（漂移审计 §2.3/§3 F2 行）

三入口各自装配：UI `expand:False`（ui.py）vs CLI/MCP True；`kg_doc_search` 直调 `Searcher.query(top_k=8, expand=False, budget=6000)` 无 seeds、不经 run_query（不记录）；impact `max_nodes` 只有 MCP 传入；UI `/api/search` 无 try/except（异常→连接关闭无响应）；UI 不热重载图（启动时冻结）；CLI query 不传 coverage。

## 预期用户结果

- `domimap/service.py`：`AppService(graph_path)`：`reload()/refresh(force)`（graph.json/knowledge.db/store.db mtime+size 签名）；`query(text, entry, **overrides)`（None 不覆盖默认；seeds 固定注入；经 `observation.run_query`）；`doc_search`（文档默认 8/False/6000，经同一路径与观测）；`impact(symbol, depth, max_nodes)`（预算在遍历中执行，返回 start/deps/total/partial/truncated/max_nodes；空符号/越界 → `ServiceError(invalid_params)`；无匹配 → `ServiceError(not_found)`）；`read_evidence`/`evidence_for`/`domain_map`。
- MCP：`Server` 持 `svc`，`g/s/seeds` 属性委托；`kg_explore/kg_read/kg_impact/kg_doc_search` 改调服务；`ServiceError` 映射 isError。
- UI：`make_server` 持 `svc`，`do_GET/do_POST` 入口 `_refresh()`；`/api/search` ServiceError→400、其他异常→500 JSON（不外泄）；`/api/impact` 经服务，响应含 partial/max_nodes；笔记保存后 `_refresh(force=True)`。
- CLI：`query`/`impact`（`--max-nodes`，partial 提示，打印 `src --KIND--> dst`）改调服务；新增 `doc TEXT`。

## Given/When/Then

- 正例：同一查询经 CLI/MCP/UI → queries.db 三条事件 entry 分别 cli/mcp/ui，有效参数（top_k/expand/budget/min_cov/domain）完全一致且 expand=True；260 依赖的 hub：服务 partial=True/total=200，MCP partial，UI partial，CLI 输出含 "partial" 与 `--READS--> hub`；graph.json 变更后长驻 UI 下一请求即见新节点；MCP `kg_doc_search` 被记录且参数 8/False/6000，CLI `doc` 同参。
- 负例：注入服务异常 → UI 500 JSON {code: internal}，不含注入文本；空符号/depth=99 → ServiceError。

## 验证 / 回滚

见 manifest。641 tests OK（含 5 项新测试）。

## 遗留

- `scenario_req` 手工拼接扩展词绕过 EXPANSION_TOKEN_WEIGHT（T15）；as_of/time 与 context 进入服务（T9/T10）。
