# m2-query-expansion：公共查询服务的领域词表扩展（M2.1 首片，目标 tiny q5）

- 问题：纯中文需求查询（如"价格同步监听"）在核心 query 路径无法命中仅有 latin 词面的类/方法节点（领域扩展此前只在 scenario 卡内），CLI/MCP 与场景语义不同源。
- 实现：`Searcher.query(..., seeds=None)`——提供 seeds 时先 classify 命中域即把域关键词拼入检索（与 scenario_req 同一语义，M2.1 公共服务的第一步）；CLI query 传 seeds。MCP 侧 M2.2 统一接线。
- 正例（先红）：tests/test_m2_query.py——mini+repo-belt 合并图上，raw query "价格同步监听"（带 seeds）Top-5 含 PriceSyncListener；不带 seeds 保持拒答/未中（对照，证明是扩展生效而非偶然）。
- 后续：分路召回/来源家族去重/时间策略在后续 M2 片；本片不扩 UI。
