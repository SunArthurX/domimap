# product-doc-chunking：索引层长文档分段——BM25 与嵌入双端

- 关联：R04（AC-R04-01）、R14（doc/fresh 绝对底线差距；两轮诊断收敛到 docx/长文粒度）。
- 来源：doc-semantic-lane（+1）与 question-quality-v3 交叉确认的剩余主因——长文档单节点：
  BM25 饱和长度归一稀释短文档对比（k=1.2 饱和下 50KB 节点 tf 优势消失、信号被稀释）、
  嵌入只取前 2000 字符（相关段落可能在后段）。
- 立场：分段在**索引层**（Searcher._build 与 embedding.build_index 的文档展开），图文件与
  节点模型零改动（chunk 项 id=<nid>#cN、file 保持原路径——路径级命中与族归属不变）；
  同文件 ≤2 席的防霸榜语义顺带限制单文件 chunk 数；阈值 3500 字符以上才分段（段 1500/重叠 250）。

## 正例 / 负例

- 正例：>3500 字符的 Doc/SqlStmt 文本按段落边界切成 ≤1500 字符段（重叠 250），每段独立
  入 BM25 倒排与嵌入向量池（EMB v3）；chunk 的 file/kind 与原文档一致。
- 正例：IDX_SCHEMA 与 EMB_SCHEMA 升级强制索引重建（旧缓存不混用）。
- 负例：≤阈值文档零变化；拒答守门/评分/融合逻辑零变化；chunk 不得改变路径级命中语义
  （file 原样）；负例底线不受影响。

## 实施（精确 allowlist）

1. `domimap/chunking.py`（新）：`split_chunks(text, size=1500, overlap=250)`（段落/换行边界
   优先）+ `expand_node(nid, node, threshold=3500)` → [(chunk_id, chunk_node_dict)]。
2. `domimap/search.py`：IDX_SCHEMA bump；_build 末段对长文档展开（chunk 注册进 self.extra
   并 _index_one——_node 回退 extra，渲染/路径语义不变）。
3. `domimap/embedding.py`：EMB_SCHEMA→v3；build_index 迭代经 expand_node。
4. `tests/test_doc_chunking.py`（新，hermetic）：切分边界/重叠/阈值；长文档分段后短查询
  可命中后段内容；短文档零变化；chunk file 语义不变。
5. 重建 pub-eval 与全量索引 + 检索级 A/B（doc/fresh 主读数，如实记录）。

## 验证与回退

- `python3 -B -m unittest tests.test_doc_chunking -v` 6 契约全绿（切分边界/重叠/硬切/展开
  file 语义/尾段可检索/短文档零变化）；refresh_evidence 后 `make verify` 447/447 全绿。
- **检索级 A/B（out/full-eval/retrieval-embed-chunked.json）——全项目最大单轮收益**：
  50→**70/140（36%→50%）**：document_reasoning 6→**15/30**、knowledge_freshness 6→**17/30**
  （+20 全部来自两个文档类）；code_location 20/30、cross_repo 14/30、locator 4/20 与
  负例 10/40 逐项不变（零回归）。索引项 6,727→17,292（含分段），v3 全量重建 9.6 分钟。
  检索级累计：基线 42 → 嵌入 49 → 文档子池 50 → **分段 70**。
- agent 级复测（chunking 收益传导）后台进行中，完成后如实记录。
- 回退：revert 单提交（schema 版本回退自动重建）。
