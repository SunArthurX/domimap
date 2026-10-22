# question-quality-v3：题面独特锚词规则——语料 df 锚定成题（系统无关）

- 关联：R14（题集质量是 11/15 剩余 miss 的根因——检索级也不可达）；R13（防偏离：规则
  系统无关，旧题集不动，五系统最终比较用新集另跑）。
- 来源：2026-10-22 三层诊断链——agent miss 19 个中 15 个 gold 未经工具输出；其中 11 个
  检索级（题面直查 + BM25 + 嵌入融合）也不可达；逐题 gold 文档内容核对（均为真实文档：
  CONTRIBUTING_COMMIT.md/Document-Chinese.md/Roadmap.md 等）证实根因是**题面无独特锚词**：
  v2 生成器 `topic_words` 按文档内词频取 top-6 拼接成题——文档内高频词天然是语料级泛词
  （关闭/必需/格式/注意/通过…），任何检索系统都无法凭它们把 gold 排进前列。
- **红线声明**：本任务不改任何既有题集/gold/评分器/预算（R14 反作弊红线）；新规则只基于
  语料 token 统计（文档频率 df），不引用任何检索系统行为；v3 是**新版本文件**，旧集原样
  保留供历史对比；最终 R14 五系统比较须在新集上另跑（后续独立任务）。

## 正例 / 负例

- 正例：`question_quality.py` 提供语料 df 统计、锚词判定（题面内容词中 ≥1 个的语料 df≤5）、
  独特词选取（df 升序、文档内 tf 降序）；v3 生成器 document/freshness 题查询词改用独特词
  选取并执行锚词准入；其余类别（code_location/cross_repo 标识符锚、locator 标题检索、
  负例四因）逻辑与 v2 逐字一致。
- 正例：验证指标=**参考可达性**（新集 doc/fresh 题在"题面直查+嵌入融合"下 gold 进 top5
  的比例显著高于旧集同类题）——这是数据集质量度量，非系统胜出宣称。
- 负例：锚词规则不得依据任何系统的检索结果定义（避免偏向词法系统）；不得改负例生成
  （图外概念拒答底线语义不变）；df 统计含全部语料文档（gold 与非 gold 同权）。

## 实施（精确 allowlist）

1. `benchmarks/corpus/question_quality.py`（新）：`corpus_df(docs)`、`anchor_ok(terms, df,
   df_max=5)`、`distinctive_words(doc, df, df_max)`。
2. `benchmarks/corpus/generate_questions_v3.py`（新）：复用 v2 的 scan_family/read_text/
   事实抽取与 add 结构；document/freshness 查询词用 distinctive_words + anchor_ok 准入；
  输出 out/benchmark/pub-questions-v3.json 与 pub-gold-v3.json（旧文件不动）。
3. `tests/test_question_quality.py`（新，hermetic）：df 计算、锚词判定边界（df=5 过/df=6
  拒）、独特词排序（df 同序时 tf 降序）、生成器准入逻辑单元级（假 docs）。

## 验证与回退

- `python3 -B -m unittest tests.test_question_quality -v` 8 契约全绿；`make verify` 全绿。
- **真实验证——如实零改进（out/question-quality-v3/reachability-final.txt）**：
  - 终版规则（族级 df≤2 + 文档级 df≤5 + 文档内 tf≥2 显著性，纯统计原则）下，
    v3 新集 doc 可达 8/28（29%）vs v2 8/25（32%）、fresh 4/15（27%）vs 3/14（21%）
    ——**均在噪声带内，锚词规则未带来预期可达性提升**。
  - 过程实验（记录于 handoff）：词界 bigram 稀有是伪锚（20/288——"器还/有就"碎片无意义）；
    族级稀有在全候选池上测得 39% 但属按可达性选样的乐观估计；终版锁定纯原则规则后
    一次测量不复现——**题面锚词不是本语料 doc 题不可达的主因**。
  - 剩余主因（观察归因）：同族近似文档多 gold 歧义（APIJSON 文档簇）、巨型文档 BM25
    累积优势、docx/长文索引粒度。**结论：题质治理杠杆实测弱于假设；R14 收敛的剩余
    路径=全族建图 + 180 题五系统正式跑 + 重复批次置信，而非题面模板调优。**
  - **中性声明**：规则迭代止于统计原则（族稀/文稀/显著），未依据任何检索系统反馈选版
    ——实验期两次按可达性对比的中间数据仅作记录，未用于规则选择。
- 回退：revert 单提交；v3 题集文件在 out/ 可删（旧集从未被修改）。
