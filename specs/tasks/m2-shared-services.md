# m2-shared-services：四入口同源同序 + Read/Trace 预算与 partial（M2.2）

- 关联：F2（AC-F2-01：无模型 CLI/JSON/UI 同范围同查询主候选同源同序）；R04（AC-R04-02：预算在遍历中执行、partial 可见）。
- 实现：mcp kg_explore 接 seeds（与 CLI 同一 Searcher 语义）；新增 kg_read（按证据 ID 读固化片段，接 M1.3 store）；kg_impact 加 max_nodes 预算超限返回 partial+截断数；CLI query --json；`domimap ui`（stdlib http.server，仅回环，搜索+证据阅读，同一 Searcher 实例语义）。
- 正例/负例（先红）：同查询四入口（Searcher 直调/CLI 文本/CLI --json/MCP handle/UI HTTP）主候选 id 序列完全一致；impact 高出度预算截断→partial:true；kg_read 不存在 ID→显式 unavailable 非崩溃；UI 非回环绑定拒绝。
