# m3-export-restore：导出/干净目录恢复/MD 互操作 + 复核版本约束（M3.4，M3 收口）

- R07-01：`backup(dir)`（SQLite backup API + manifest 计数）→ 干净目录 `KnowledgeStore.restore(dir)` → 正文/修订/审定/引用计数一致且可检索。
- R07-02：`export_markdown(dir)`（front-matter: note_id/revision(=base_revision)/status + claims）；`import_markdown(path)` 显式导入——外部改文且 base_revision=当前 → amend 新修订；base 过期 → ConflictError；导出目录被扫描只产生 Doc 节点，**不自动回灌**为知识/独立证据（kb 计数不变）。
- F4-02：确认（绑定 sha-b2）后依据再变（sha-b3）→ 重新入待复核（旧审定不继承新版本）；挂载检索时该 claim 标 stale。
