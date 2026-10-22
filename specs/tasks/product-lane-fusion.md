# product-lane-fusion：分路命中再融合——代码/文档/知识三路独立召回与保底融合

- 关联：R04（AC-R04-01"分路召回并融合：文档不饥饿、主候选去重"——本任务把单向文档保底升级为对称三路；AC-R04-02 引用完整——融合不改引用与出处语义）。
- 来源：用户 2026-10-22 指示——"有文档和代码时，希望文档和代码**分别命中之后再融合**，而不是仅命中文档"。与 2026-10-21 A/B 根因一致：全局 45% 断崖精剪让巨型泛词文档独占结果（代码路被剪光、Knowledge 笔记被剪光）。
- 立场：不改拒答守门、不改 BM25 打分、不改词法/桥接候选生成（回退候选集经核查本就是并集）——只改**打分之后的选择与融合层**。

## 正例 / 负例

- 正例：三路（code=非 Doc/Knowledge 节点；doc=Doc；kn=Knowledge 笔记）各自独立完成 ①同文件 ≤2 席去重 ②路内断崖精剪（低于本路 top 分 45% 截尾）；融合时每条非空路保底入席（code/doc 各 ≤2、kn ≤1），其余席位按全局分排序补足；跨族覆盖逻辑保留（作用于融合结果）。
- 正例：文档高分霸榜的查询仍返回代码路命中（用户核心诉求）；代码霸榜的查询文档路不饥饿（原 want_docs 语义保留且对称化）；Knowledge 笔记作为高精度指针在存在且有存活时保底 1 席。
- 负例：任一路为空（无候选或全被守门拒绝）不得虚构席位；拒答语义（通用词/标识符缺席/覆盖率）逐字不变；断崖仍是精度守门——只是比较对象从全局 top 改为本路 top。
- 负例（度量侧）：适配器对 Knowledge 节点做**源路径归因**（marker source → 仓前缀路径），无 marker 不猜路径、不参与 top5 路径；其余四系统与既有适配器行为零变化。

## 实施（精确 allowlist）

1. `domimap/search.py`：query() 的选择融合段重写——`_lane_of`/`_lane_prepare`（fam 去重+路内断崖）+ 保底融合 + 跨族覆盖适配；删除被取代的旧 want_docs 文档保底块与全局断崖块；time_note/render/扩展/预算逻辑不动。
2. `benchmarks/adapters/domimap_adapter.py`：query() 中 Knowledge 节点解析 marker `source=` → 归因为源文档路径（经仓名映射），notes 记 `via:knowledge`；路径级 Hit@5 因此可度量笔记贡献。
3. `tests/test_lane_fusion.py`（新）：文档霸榜仍见代码路；代码霸榜文档不饥饿；路内断崖；Knowledge 保底席（复现 A/B 阻断场景：巨型文档+高分笔记）；同文件 ≤2；拒答语义不变；融合引用完整。
4. A/B 复测（复用 out/llm-enrich-ab 既有 40 篇真实笔记，零新 token）：三方对照——旧检索基线 19/40（已录）/ 新检索无 knowledge.db / 新检索+knowledge.db；分类别对比，如实记录。
5. 文档：knowledge-graph.md §5 检索数据流、README、CHANGELOG。

## 验证与回退

- `python3 -B -m unittest tests.test_lane_fusion tests.test_llm_enrich -v`（7+32 契约）；存量检索契约（replay raw ≥75%、标识符排序、拒答）全绿；refresh_evidence 后 `make verify` 全绿。
- **三方 A/B（2026-10-22，复用 40 篇真实笔记，零新 token；工件 out/llm-enrich-ab/ab3-lane-fusion.json）**：
  - a 旧检索基线 = 19/40；b 分路融合·无 LLM = **19/40（零回归）**；c 分路融合+LLM = **19/40（Hit@5 零提升）**。
  - 结果构成（用户诉求的直接交付）：此前泛词文档题仅返回 1 个文档；现在 1 Doc + 8 代码节点 + 1 Knowledge 笔记——文档与代码分别命中后融合。
  - LLM 笔记可见性：0/40 → **40/40 题**（top10 且带源路径归因 via:knowledge）；但保底席落在分数序尾部（如 dv2-0060 笔记 42.7 分 vs 8 个泛词 SqlStmt 50-300 分），故不进 top5。
  - 如实结论：分路融合修复了"一路独占"的结构缺陷且无回归；Hit@5 的最终突破仍卡在词法分数天花板（泛词代码节点 BM25 分数高于语义正确的笔记）——语义排序/重排是下一个必要台阶（backlog）。
- 实现过程中发现并修复两处自身缺陷：保底席位曾被高分挤出 top_k（仅入池未落位）、跨族覆盖交换会挤掉保底席位（加 gua_ids 守卫）——真实图探查暴露，夹具未覆盖。
- 回退：revert 本提交即回到全局断崖语义；A/B 工件（含三方对照）入 out/llm-enrich-ab/。
