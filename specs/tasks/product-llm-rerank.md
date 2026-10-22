# product-llm-rerank：查询期可选 LLM 语义重排——BM25 原始 scored 序 top-N 送 LLM 重排

- 关联：R04（AC-R04-01 检索质量——重排只改排序不改召回与守门）、R05（AC-R05-02 可选 LLM 层
  纪律——只产排序不产事实）、R08（有界资源纪律：池上限/缓存/失败即退回 BM25 序）。
- 来源：product-semantic-bridge A/B 根因修正后的下一台阶（handoff backlog：语义排序/重排）。
  **前置测量（2026-10-22，out/semantic-bridge-ab/pub-miss-raw-ranks.json，74 个 pub 图内 miss）**：
  BM25 原始 scored 序中 gold 名次——≤20 名 2 个、21-50 名 4 个、51-200 名 9 个、>200 名 40 个、
  完全无词面交集 19 个。**诚实预期**：池=50 的重排上限 +6/97（24%→30%）；真实提升按 A/B 实测，
  可能明显低于上限。40 个 >200 名与 19 个无交集人群是**嵌入索引**（下次架构决策）的人口，
  非重排可及。
- 立场：默认关（`DOMIMAP_LLM_RERANK=1` 或 `query --rerank`）；重排对象是**原始 scored 序**
  （选择层之前——实测 dv2-0125 gold 原始第 2 名被同文件 ≤2/断崖挤出，重排须能重新纳入）；
  LLM 只输出给定不透明 id（c1..cN）的排列——无新 id、无文本、无路径，注入面=0；
  失败/未配置/解析失败 → 原序继续，下游（三路融合/保底/跨族）逻辑零变化。

## 正例 / 负例

- 正例：启用时，scored 序前 N（默认 50，上限 100）的候选带紧凑描述（kind/name/file/score/
  截断片段）送 LLM 按查询相关性重排；验证后的排列替换 scored 前 N 段，其余按原序续接；
  结果 dict 记 `llm_rerank`（池大小/是否应用）；查询文本与片段以分隔符包裹声明"数据非指令"。
- 正例：响应只接受已知 id 的排列；未知 id 丢弃、缺席 id 按原序补尾——不完整响应降级为
  部分重排而非失败。
- 负例：默认关时行为逐字节一致（既有 404 契约守护）；候选数 ≤ top_k 不调用；
  无 key/传输失败/解析失败 → 原序，绝不空结果、绝不拒答变化。
- 负例：重排后的下游仍过三路融合与保底——重排不得使某条非空路失去代表（保底落位语义保留）。
- 负例（度量侧）：与 semantic bridge 正交可叠加，但本轮 A/B 单独开 rerank（不叠桥），
  归因清晰。

## 实施（精确 allowlist）

1. `domimap/llm_rerank.py`（新）：`enabled()`/`rerank(query, candidates, ...)`；复用
   `llm_enrich.LlmClient`（max_tokens 1024——GLM thinking 块实测需 ≥1024）；内存+磁盘缓存
   （sha(query+候选 id 集) → 排列）；RERANK_POOL 默认 50、上限 100。
2. `domimap/search.py`：query() 增加 `rerank=None` 参数；scored 排序后、选择融合前插入
   重排段；结果 dict 增 `llm_rerank` 键。
3. `domimap/__main__.py`：`query --rerank [--rerank-pool N]`。
4. `tests/test_llm_rerank.py`（新，hermetic 假客户端）：默认关零调用；排列生效且保底语义
   保持；未知 id 丢弃；不完整响应补尾；解析失败/异常原序；缓存零重复；池上限；≤top_k 不调用。
5. 文档：docs/knowledge-graph.md 数据流第 2 步补注、README 可选层段落补一行。

## 验证与回退

- `python3 -B -m unittest tests.test_llm_rerank -v` 11 契约全绿（rerank/bridge/lane 29/29）；
  refresh_evidence 后 `make verify` 415/415 全绿（默认关路径零回归由存量契约守护）。
- **真实 A/B（2026-10-22，工件 out/semantic-bridge-ab/{pub,dev}-rerank.json，真实 GLM-5.3，
  池 50，pub 52 次调用中位 10.8s/次）——如实零效果零回归**：
  - pub 图内 97 正例：基线 23/97 → 重排 23/97（分类别逐项相同；负例 11/40 一致零破坏）。
  - dev 36 正例：基线 19/36 → 重排 19/36（逐类别相同）。
  - **根因（两层）**：①前置测量已知——74 miss 中仅 6 个 gold 在 BM25 原始序 ≤50 名（40 个
    >200 名、19 个无词面交集，重排池不可及）；②即使可及的 6 个，GLM-5.3 基于 150 字符
    片段的零样本相关性判断也没有把 gold 提进 top5——反而偏好 CONTRIBUTING/README 等
    "看起来像答案"的泛文档（dv2-0125：gold 原始第 2 名，重排后 top5 全是泛文档）。
  - **结论（三重证据链终局）**：词法桥（4 轮）、查询扩展（semantic-bridge）、LLM 重排
    （本轮）在检索级口径全部零效果——剩余 miss 人口（>200 名 + 无交集 = 59/74）只有
    **嵌入索引**（embedding 召回/评分，一次建索引 O(1) 查询可达全名次）可及。这是下一个
    架构决策，不再是查询期干预。
  - 重排保留为可选层：默认关零成本；对 gold 已在池内的真实场景（如人工查询纠偏）仍有
    产品价值；负例底线未破（重排不碰拒答路径，结构性保证）。
- 回退：revert 单提交；缓存文件可删；无数据格式变更。
