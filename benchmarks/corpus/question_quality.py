"""question_quality — 题面独特锚词规则（系统无关，question-quality-v3）。

根因（2026-10-22 三层诊断）：v2 生成器按文档内词频取题面词——文档高频词天然是语料级
泛词，题面无独特锚词，任何检索系统都无法把 gold 排进前列（11/15 剩余 miss 检索级不可达）。

规则（纯语料 token 统计，不引用任何检索系统行为——对五系统对称）：
- corpus_df：文档级 df（token 出现于多少篇文档）；family_df：族级 df（出现于多少个族）。
  族级稀有是关键——同族近似文档（如同一项目的 README/中文文档/扩展文档）共享同一批
  "语料级稀有"词，只有族级稀有（≤FAM_MAX 个族含该词）才能唯一锚定 gold
  （实验：仅文档级 df 规则 doc 题可达 33%；加族级规则 39%；词界 bigram 稀有是伪锚 7%）。
- anchor_ok：题面内容词中 ≥1 个的语料 df ≤ DF_MAX（默认 5）。
- distinctive_words：fam_df 升序、doc_df 升序、文档内 tf 降序选词。
"""
from collections import Counter

DF_MAX = 5          # 锚词文档级 df 上限
FAM_MAX = 2         # 锚词族级 df 上限（族内近似文档不产生唯一锚——必须跨族稀有）
MIN_WORDS = 3       # 独特词成题最少词数（不足则该文档不成 doc/fresh 题）


def corpus_df(docs):
    """docs: [{tokens: iterable[str], ...}] → token → 出现文档数。"""
    df = Counter()
    for doc in docs:
        for t in set(doc.get("tokens") or ()):
            df[t] += 1
    return df


def family_df(families_docs):
    """families_docs: {family: [doc, ...]} → token → 出现族数（族内去重）。"""
    fdf = Counter()
    for docs in families_docs.values():
        seen = set()
        for doc in docs:
            seen.update(doc.get("tokens") or ())
        for t in seen:
            fdf[t] += 1
    return fdf


def anchor_ok(terms, df, df_max=DF_MAX):
    """题面内容词中至少一个的语料 df ≤ df_max。"""
    return any(0 < df.get(t, 0) <= df_max for t in terms)


def distinctive_words(doc, doc_df, fam_df=None, fam_max=FAM_MAX,
                      df_max=DF_MAX, limit=4):
    """独特词：fam_df（提供时）≤ fam_max 且 doc_df ≤ df_max 且**文档内 tf ≥ 2**（显著，
    非一次性碎片）的词，按（fam_df 升序，doc_df 升序，文档内 tf 降序，字典序）取前 limit。

    规则均为语料统计原则（独特性/显著性），不依据任何检索系统行为。fam_df 不提供时
    退化为纯文档级规则。
    """
    fam_df = fam_df or {}
    banned = doc.get("title", "") + doc.get("stem", "")
    tf = Counter(t for t in (doc.get("tokens") or [])
                 if len(t) >= 2 and t not in banned)
    def key(t):
        return (fam_df.get(t, 0) if fam_df else 0, doc_df.get(t, 0), -tf[t], t)
    cands = [t for t in tf
             if tf[t] >= 2
             and 0 < doc_df.get(t, 0) <= df_max
             and (not fam_df or 0 < fam_df.get(t, 0) <= fam_max)]
    return sorted(cands, key=key)[:limit]
