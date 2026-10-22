# product-embedding-index：可选嵌入索引——语义召回并入检索（RRF 融合）

- 关联：R04（AC-R04-01 检索质量——语义召回作为第四候选源并入，不改守门）、R05（AC-R05-02
  可选 LLM/模型层纪律——嵌入是可选层，默认关，核心离线零依赖）、R08（有界资源纪律：
  截断/幂等/缓存/后端缺失清晰报错）。
- 来源：三重证据链终局（词法桥 4 轮 + 查询扩展 + LLM 重排全部零效果）——59/74 的 pub 图内
  miss 中 gold 在 BM25 原始序 >200 名 40 个、无词面交集 19 个，查询期干预不可及，只有
  嵌入索引可达全名次。59 人口的 gold 构成：.sql 41 + .md 39 + .docx 1 → 嵌入目标 =
  Doc + Knowledge + SqlStmt + Table（共 ~2750 节点，pub 图实测）。
- **外部阻塞如实记录（2026-10-22）**：bigmodel embedding-3 API 返回 1113"余额不足或无可用
  资源包"——API 后端已实现但当前不可用；**本地后端（fastembed + BAAI/bge-small-zh-v1.5，
  512 维，离线免费）为主用**，对开源产品更优（无 API 依赖）。fastembed 为可选依赖（import
  守护，缺失时清晰报错，核心与 hermetic 测试零依赖——测试注入假后端）。
- 立场：默认关（`DOMIMAP_EMBED=1` 或 `query --embed`）；建索引 `domimap embed -g <graph>`
  一次性、幂等（nid+文本 sha 键，未变不重算）；查询期 RRF（K=60）融合 BM25 序与语义序
  ——参数无关的标准融合法；拒答守门先于语义融合（负例结构性安全）；下游三路融合/保底/
  重排逻辑零变化（融合只替换 scored 序与其分值）。

## 正例 / 负例

- 正例：`domimap embed -g graph.json [--targets docs|sql|all]` → 图旁 `<graph>.emb.json`
  （schema/后端/模型/维度/每节点 sha+向量）；`query --embed` 时 BM25 top-500 与语义 top-500
  RRF 融合后的序与分值进入后续流程；结果 dict 记 `embedding`（语义命中数/后端/是否融合）。
- 正例：bge 查询侧加标准检索指令前缀（文档侧不加）——跨语言（中文查询 vs 英文文档）实测
  该前缀显著改善分离度。
- 负例：默认关/索引缺失/后端缺失/向量损坏 → BM25 原序继续，绝不空结果、绝不拒答变化。
- 负例：拒答守门（覆盖率/标识符/通用词）先于融合——语义召回不得把应拒答的查询变成假命中
  （负例底线结构性保持）。
- 负例：嵌入不改变图事实与知识审定语义（产物只是检索用的浮点向量，conf/prov 不动）。

## 实施（精确 allowlist）

1. `domimap/embedding.py`（新）：后端接口（`LocalFastembedBackend` 主用 / `ApiBackend`
   bigmodel v4/embeddings，余额阻塞如实注释）；`build_index(graph, targets, ...)` 幂等建库；
   `load/store`（JSON，向量 5 位小数）；`fuse_rrf(bm25_order, sem_order, k=60)`；
   查询向量缓存。
2. `domimap/search.py`：`query(..., embed=None)`；拒答门后、时新加权前插入 RRF 融合段；
   `Searcher.load_embeddings(path)` 公开方法（基准回放/显式加载用）；sidecar 自动发现
   （cache_path 推导图路径）。
3. `domimap/__main__.py`：`embed` 子命令（--targets/--limit/--dry-run）+ `query --embed`。
4. `tests/test_embedding.py`（新，hermetic 假后端，无网络无 fastembed）：建库幂等/截断/键；
   RRF 融合语义首位可进 top；默认关零变化；索引缺失/后端缺失优雅回退；拒答门先于融合
   （负例不因语义变命中）；bge 查询前缀仅本地后端（假后端可断言调用文本）。
5. 文档：docs/knowledge-graph.md 数据流、README 可选层段落。

## 验证与回退

- `python3 -B -m unittest tests.test_embedding -v` 12 契约全绿；refresh_evidence 后
  `make verify` 427/427 全绿（默认关路径零回归由存量契约守护）。
- **真实 e2e A/B（2026-10-22，本地 bge-small-zh-v1.5，pub 建索引 2747 项 83s / dev 3643 项
  59s；工件 out/semantic-bridge-ab/{pub,dev}-embed.json）——首个净正收益轮**：
  - pub 图内 97 正例：基线 23/97 → 嵌入融合 **36/97**（+13，相对 +56%）；负例 11/40 两臂
    一致零破坏。分类别：code_location 19/27 保持、document_reasoning 1/25→8/25、
    knowledge_freshness 1/14→3/14、locator_diagnostic 2/20→6/20。
  - dev 36 正例：基线 19/36 → **26/36**（+7，53%→72%）；document_reasoning 0/8→4/8、
    locator_diagnostic 0/4→3/4，其余类别全部保持。
  - **两轮门迭代（如实）**：裸 RRF 使 code_location 19/27→5/27（语义文档稀释词法精确
    命中）→ 标识符锚定无效（回归题是纯中文找类查询，无标识符）→ 定义性信号门部分恢复
    （19→8）→ **代码意图门**（查询含 处理类/位置/列名/字段/表/定义/写入… 即跳过融合，
    与 DDL_SEMANTIC_HIT 同型语义）后 code_location 19/27 完整恢复且文档增益保持。
    区分证据：丢失 11 题全部含"处理类 位置"，增益 14 题全部无意图词。
  - API 后端如实：bigmodel embedding-3 返回 1113 余额不足——本地 fastembed 后端为主用
    （离线、免费、开源友好），API 后端实现保留。
- 已知边界：cross_repo_trace 0/11 未动（gold 多为图外族 SQL/需标识符路由）；R14 绝对底线
  （Hit≥0.80）仍需 agent-loop 口径复测与后续轮次。
- 回退：revert 单提交 + 删 `.emb.json`；无数据格式变更（sidecar 可删）。
