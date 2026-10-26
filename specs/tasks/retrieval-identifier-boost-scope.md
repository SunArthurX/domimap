# retrieval-identifier-boost-scope — 扩展词不得冒领原始查询的证据权重

retrieval-evolution-pilot 的独立修复任务（L2 候选改进）。日期：2026-10-26。

## 问题与根因（诊断包 out/dev-ws/diag-pilot.json）

真实语料查询「商品 审核状态 流转」：含原始实词（商品/审核/状态，df=41/4/20）的
`doc/商品主数据融合项目设计文档V1.0.docx` 排名 15；top6 全为 seeds 扩展英文词
匹配的 generic 节点（fastjson asm 的 `Item`、`ItemProduct` 等）。

## 候选 1（已失败并回滚，ReplayRun 留档）

仅限定名称精确加成（IDENTIFIER_NAME_BOOST 只对原始查询标识符生效，name_tokens
参数）。真实回放 rp:1d848d2e87552f37：目标仍 MISS（扩展词凭内容匹配照旧霸榜）且回归
2 项（keep-stock/keep-order，均为扩展词加成的受益者）。按计划走失败分支：回滚演练
rp:ed82d326940e231d 与基线 rp:3c157f4d9dc6a6ed 逐样本一致（verdict=no_change）。
name_tokens 限定本身正确（机制单测钉住），保留但不足以修复。

## 候选 2（最终修复设计）

两处协同（domimap/search.py）：
1. 名称精确加成只对原始查询标识符生效（同候选 1，保留）。
2. **扩展 token 降权**：seeds 域扩展拼入的英文词在 BM25 计分中按
   EXPANSION_TOKEN_WEIGHT=0.35 计（≈3 个扩展命中 ≈ 1 个原始词命中）；
   同时出现在原始查询与扩展中的 token 按原始词全权。覆盖率门、拒答判定、
   负例守门、分路融合、时间策略不变；中英桥回退路径（拒答救援）不降权。
   依据：原始查询词是用户表达的证据；扩展词只是词法桥（召回通道），不应当代表
   用户意图与原始词同权竞争排序。0.35 取 1/3 量级、在真实语料目标查询上一次性
   预登记，未用留出集调参。

预期：目标文档原始词全权计分 → 回到 top_k；扩展词受益者位次变化属预期行为变更
（其旧位次是缺陷产物，非合法回归基线——样本集 v2 的保持者只收原始词证据支撑的成功）。

## 负例

- 原始查询自带标识符（"Item 商品信息"、"StockClient 库存"）：加成保留。
- 无 seeds 路径（benchmark 直调、单测多数路径）：weak 集为空，行为逐字不变。
- 拒答救援（中英桥回退）不降权：低覆盖查询的救援能力不受影响。
- 应拒答负例仍拒答（覆盖率门不在降权范围内）。

## 验证

- tests/test_identifier_ranking.py：机制单测（_score name_tokens 语义 + ×3 比率；
  扩展 token 降权比率 0.35；原始词全权）+ 端到端不回归。
- 固定回放集 v2（out/dev-ws/replay-pilot-samples.json，保持者=原始词证据支撑的
  成功）：baseline/candidate/rollback 三 run（见 pilot 任务）。
- `make verify` 全量回归。

## 回滚

revert search.py 本任务差异；rollback 回放 run 已实证等价基线；无数据迁移。

## 文件

domimap/search.py、tests/test_identifier_ranking.py（增补用例）。
（manifest 同 pilot 任务登记的全部并行文件，仅为范围检查。）


## drift-correction 重证（2026-10-26，C7）

偏离审查（F02/F03/F04）判定原回放证据无效：文件级子串评分 + 样例替换 + 激活门槛
缺失。C5/C7 纠正后以精确节点评分（exact-node-v1）与独立裁决的冻结样本集 v3 重证：
baseline rp:cdcf888fa0b86cc2（3/5，目标 rank 15/无）→ candidate rp:ab3f271dff7bbc5f
（4/5，目标 15→4、5→1，零回归）→ rollback rp:58ff1e67a078bdeb（与基线逐样本等价）。
新启用决定 imp:d914a167c7a25b8401fe（lineage 完整）。keep-itemproduct 两轮皆 MISS，
如实保留为未解决问题（gold 未因结果调整）。旧 imp:ccf1ee268b695abbf2cd 已失效留档。
