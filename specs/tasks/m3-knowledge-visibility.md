# m3-knowledge-visibility：人工知识进入检索 + 机器重建不丢（M3.2，目标 AC-R05-02）

- 设计：`Searcher.attach_knowledge(kb)`——查询时从 KnowledgeStore 读 active 笔记建临时节点（kind=Knowledge，id=kn:{note_id}，meta 带 body/claims/status），进词法索引与 Doc 路保底；**不写机器图**（重建天然不丢：知识库独立于 generation）。
- 契约（先红）：①≥10 条带独立 claims 知识，新会话（新 Searcher+重载图）attach 后按正文标记命中；②机器图 force 重建后 kb 计数不变且仍可命中；③claims 五类型保持、状态独立，绝无 extracted/fact 混入；④withdrawn 不进检索。
