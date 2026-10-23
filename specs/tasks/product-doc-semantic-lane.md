# product-doc-semantic-lane：文档意图查询的语义召回限定文档向量子池

- 关联：R04（AC-R04-01 检索质量）、R05（可选层纪律）、R14（doc 7/30、fresh 4/30 是绝对
  底线差距主体）。
- 来源：能力矩阵 C4 探针与 180 题一致的根因——泛中文文档查询的语义近邻被 SQL/代码向量
  混池占据（embedding store 目前不分 kind；doc 意图查询的 cosine 榜首常是 SqlStmt/代码）。
- 立场：嵌入融合的资格门（代码意图词/定义性标识符→词法权威）已判别"文档意图"；对已判别
  为文档意图的融合查询，语义召回只在 Doc/Knowledge 向量子池内做——代码语义对文档题是噪声。
  默认关路径与其余融合逻辑零变化。

## 正例 / 负例

- 正例：emb store 升级 v2（每项带 kind）；`_cosine_top` 支持 kind 白名单；融合段在
  `skipped` 为空（即文档意图）时传 kinds=("Doc","Knowledge")。
- 正例：A/B 口径=检索级 180 题全集 embed 臂对照（doc/fresh 类别为主读数）。
- 负例：代码意图/定义性标识符查询不进融合（既有门不变）；store v1（无 kind）按不兼容
  处理→重建；负例拒答路径零变化；幂等键仍 nid+sha。

## 实施（精确 allowlist）

1. `domimap/embedding.py`：EMB_SCHEMA→v2；build 存 kind；`semantic_recall(..., kinds=None)`
   过滤子池。
2. `domimap/search.py`：融合段文档意图时传 kinds。
3. `tests/test_embedding.py`：补 2 契约（v2 带 kind/子池过滤）。
4. 重建全量索引（~8 分钟）→ 检索级 A/B → 如实记录。

## 验证与回退

- `python3 -B -m unittest tests.test_embedding -v`（含 2 个新契约）全绿；refresh_evidence 后
  `make verify` 全绿；全量 v2 索引重建 3 分钟（schema 升级强制重嵌 6,727 项）。
- **检索级 A/B（out/full-eval/retrieval-embed-doclane.json）——如实 +1/140**：
  49→50（knowledge_freshness 5→6）；document 6/30 与其余类别逐项不变、负例 10/40 一致
  （零回归）。结论：子池限定温和正收益；doc 剩余 miss 的主因（同族近似文档歧义/巨型文档/
  docx 粒度）不在语义混池——与 question-quality-v3 的诊断一致。
- 回退：revert 单提交；v2 store 与 v1 互不兼容→重建即回。
