# m1-evidence-generations：固化证据、SQLite 骨架与不可变 generation 发布

- 关联：R02（AC-R02-01 旧 ID 读固定片段不冒充当前）、R03（AC-R03-01 发布中断/并发不混代；AC-R03-02 图丢失/种子变化不误报 no-op=D1）。
- 问题：证据只有相对路径（D5）；合并图被删后 update 仍报 no-op（D1）；无发布事务（读者可见半成品）。
- 设计：
  - `domimap/store.py` EvidenceStore（stdlib sqlite3）：sources（sid/字节 sha256/大小）+ evidence（内容寻址 blob + locator）+ generations（gen_id/sha256/节点边数/status）+ meta.active 指针。
  - 发布协议（顺序强制）：写 tmp gen 文件 → fsync → rename 不可变 gen-N.json → 校验（可解析+计数>0）→ SQLite 事务登记+切换 active。中断于任一阶段，读者只见上一完整代；blob 内容寻址不可变，旧证据永久可读（源删除亦可）。
  - build_many 集成：no-op 判定增加 store.active 校验与 seeds 摘要门；update 无 manifest 根时报错非 no-op。graph.json 在指针切换成功后由 active 代复制（兼容旧 CLI，M2 收口）。
- 正例/负例（tests/test_evidence_store.py，先红后绿）：
  1. AC-R02-01：建库→取源证据 ID→改源→读旧 ID 得旧文本；删源→仍可读；新构建版本 sha 不同。
  2. AC-R03-01：三阶段中断（tmp 残留/校验失败/事务前 kill）→ active 恒为上一完整代；并发双写者→ active 始终完整合法。
  3. AC-R03-02：manifest 不变但删 active 代文件→update 重建且节点集=全量重建；改 seeds.json→重建；空 roots update→非零报错不 no-op。
- refresh_evidence.py 扩展：按 progress 全量 verified 案例重跑其 command 并刷新指纹（本切片学到的纪律固化）。
- 验证：unittest tests.test_evidence_store -v；make verify；task diff --base bc2eab9；progress 三案例 verified。
- 回退：revert 任务文件；store.db/gens 属生成物（out/，gitignore）。
