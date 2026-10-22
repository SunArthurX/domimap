#!/usr/bin/env python3
"""pub 题集 v3 生成器（question-quality-v3）：doc/fresh 题改语料 df 锚定成题。

与 v2（generate_questions_v2.py）的差别（其余类别逐字复用 v2 输出）：
- v2 的 document/freshness 查询词 = 文档内词频 top-N——高频词天然是语料级泛词，题面无
  独特锚（11/15 剩余 miss 的检索级不可达根因，2026-10-22 三层诊断）。
- v3 改用 question_quality.distinctive_words（df 升序、tf 降序）+ anchor_ok 准入
  （≥1 内容词语料 df≤5）——纯语料统计，系统无关。
- 旧集文件不动；输出 out/benchmark/pub-questions-v3.json / pub-gold-v3.json。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "benchmarks", "corpus"))

from generate_questions_v2 import (CN, DATE, FRESH_KW, QUOTA, RESTRICT_KW,  # noqa: E402
                                   MOCK_MAX, scan_family, fam_root)
from question_quality import (DF_MAX, FAM_MAX, MIN_WORDS, anchor_ok,  # noqa: E402
                              corpus_df, distinctive_words, family_df)

WS = os.path.expanduser(os.environ.get("DOMIMAP_DEV_CORPUS") or "")
OUTDIR = os.path.join(ROOT, "out", "benchmark")


def build_v3(families, v2_questions, v2_gold, root_of=None):
    root_of = root_of or fam_root
    facts = {f: scan_family(root_of(f)) for f in families}
    all_docs = [d for f in facts for d in facts[f]["docs"]]
    df = corpus_df(all_docs)
    fdf = family_df({f: facts[f]["docs"] for f in facts})

    questions, gold = [], []

    def add(category, query, families_, paths, facts_, disposition, verify):
        qid = "dv3-%04d" % len(questions)
        questions.append({"id": qid, "category": category, "query": query})
        gold.append({"id": qid, "category": category, "families": families_,
                     "gold_paths": paths, "necessary_facts": facts_,
                     "disposition": disposition, "verify_method": verify})

    # 类别 1/2/5/6：逐字复用 v2 输出（含负例四因与标识符/注释/标题题）
    keep_cats = {"code_location", "cross_repo_trace", "locator_diagnostic", "negative"}
    for q, g in zip(v2_questions, v2_gold):
        if q["category"] in keep_cats:
            add(q["category"], q["query"], g["families"], g["gold_paths"],
                g["necessary_facts"], g["disposition"], g["verify_method"])

    # 3) document_reasoning（v3）：独特词成题 + 锚词准入
    dr, dr_seen = 0, set()
    for f in sorted(facts):
        for doc in facts[f]["docs"]:
            if dr >= QUOTA["document_reasoning"]:
                break
            if doc.get("mock_ratio", 0) > MOCK_MAX or doc["rel"] in dr_seen:
                continue
            restrict = [s for s in doc["sentences"]
                        if any(k in s for k in RESTRICT_KW)]
            if not restrict:
                continue
            words = distinctive_words(doc, df, fdf, FAM_MAX, DF_MAX)
            if len(words) < MIN_WORDS or not anchor_ok(words, df, DF_MAX):
                continue
            add("document_reasoning", " ".join(words[:4]) + " 限制 条件", [f],
                ["%s/%s" % (f, doc["rel"])],
                ["%s：%s" % (doc["rel"], restrict[0][:80])],
                "answer", "正文限制句；v3 独特词（族 df≤%d + 文档 df≤%d 锚定）" % (FAM_MAX, DF_MAX))
            dr_seen.add(doc["rel"])
            dr += 1
        if dr >= QUOTA["document_reasoning"]:
            break

    # 4) knowledge_freshness（v3）：最新日期文档 + 独特词成题 + 锚词准入
    kf, used_f = 0, {}
    for f in sorted(facts):
        dated = sorted((d for d in facts[f]["docs"]
                        if d["dates"] and d.get("mock_ratio", 0) <= MOCK_MAX),
                       key=lambda d: max(d["dates"]), reverse=True)
        for newest in dated:
            if kf >= QUOTA["knowledge_freshness"] or used_f.get(f, 0) >= 3:
                break
            words = distinctive_words(newest, df, fdf, FAM_MAX, DF_MAX)
            if len(words) < 2 or not anchor_ok(words, df, DF_MAX):
                continue
            latest = max(newest["dates"])
            add("knowledge_freshness",
                " ".join(words[:4]) + " 最新 生效 说明 日期", [f],
                ["%s/%s" % (f, newest["rel"])],
                ["%s 内最新日期 %d-%02d-%02d" % (newest["rel"], *latest)],
                "answer", "文档内日期扫描；v3 独特词（族 df≤%d + 文档 df≤%d 锚定）" % (FAM_MAX, DF_MAX))
            kf += 1
            used_f[f] = used_f.get(f, 0) + 1
        if kf >= QUOTA["knowledge_freshness"]:
            break

    counts = {}
    for q in questions:
        counts[q["category"]] = counts.get(q["category"], 0) + 1
    return questions, gold, counts, df


def main():
    if not WS:
        raise SystemExit("DOMIMAP_DEV_CORPUS 未设置（指向语料根，如 ~/work/dm-corpus-public）")
    v2q = json.load(open(os.path.join(OUTDIR, "pub-questions.json"), encoding="utf-8"))
    v2g = json.load(open(os.path.join(OUTDIR, "pub-gold.json"), encoding="utf-8"))
    fams = sorted({f for g in v2g["gold"] for f in g.get("families", [])})
    questions, gold, counts, df = build_v3(fams, v2q["questions"], v2g["gold"])
    out_q = {"schema": "domimap.pub-questions.v3", "generated_utc":
             __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
             "corpus": "dm-corpus-public v3（doc/fresh 独特词锚定，规则见 question_quality.py）",
             "counts": counts, "questions": questions}
    out_g = {"schema": "domimap.pub-gold.v3", "gold": gold}
    json.dump(out_q, open(os.path.join(OUTDIR, "pub-questions-v3.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out_g, open(os.path.join(OUTDIR, "pub-gold-v3.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()
