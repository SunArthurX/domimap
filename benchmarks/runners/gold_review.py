#!/usr/bin/env python3
"""dev 试点 gold 人工核验：工作表生成 + 裁决应用。

独立性声明：实现会话内单评审草稿（非确认集独立双标）——见任务 spec。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "benchmarks"))

# 语料根/外部文档族：自备（env；企业私有或开源语料均可，见 benchmarks/DATA_LAYOUT.md）
WS = os.path.expanduser(os.environ.get("DOMIMAP_DEV_CORPUS") or "")
EXTRA_ROOTS = [os.path.expanduser(p) for p in
               os.environ.get("DOMIMAP_EXTRA_FAMILIES", "").split(",") if p]


def _root_of(fam):
    for p in EXTRA_ROOTS:
        if os.path.basename(os.path.normpath(p)) == fam:
            return p
    return os.path.join(WS, fam)


def _read_doc(path):
    from corpus.generate_questions_v2 import extract_document, read_text
    low = path.lower()
    if low.endswith((".docx", ".html", ".htm")):
        got = extract_document(path)
        return (got[0] or "") if got else ""
    return read_text(path)


def excerpt(fam, rel, fact, width=160):
    """gold 文件中事实依据处的 ±width 字符摘录（找不到则文件头）。"""
    path = os.path.join(_root_of(fam), rel)
    if not os.path.isfile(path):
        return "<文件不存在>"
    text = _read_doc(path)
    needles = [t for t in str(fact).split() if len(t) >= 2][:6] or [str(fact)[:12]]
    pos = -1
    for needle in needles:
        pos = text.find(needle)
        if pos >= 0:
            break
    if pos < 0:
        for ch in str(fact):
            if ord(ch) > 0x2E7F:
                pos = text.find(ch)
                if pos >= 0:
                    break
    if pos < 0:
        pos = 0
    return text[max(0, pos - width):pos + width].replace("\n", " ⏎ ")


def worksheet(pilot_ids, questions, gold):
    qmap = {q["id"]: q for q in questions}
    gmap = {g["id"]: g for g in gold}
    rows = []
    for qid in pilot_ids:
        q, g = qmap[qid], gmap[qid]
        excerpts = []
        for gp in g["gold_paths"][:2]:
            fam, rel = (gp.split("/", 1) + [""])[:2]
            excerpts.append({"path": gp,
                             "text": excerpt(fam, rel, " ".join(g["necessary_facts"]) or q["query"])})
        rows.append({"id": qid, "category": q["category"], "query": q["query"],
                     "gold_paths": g["gold_paths"], "facts": g["necessary_facts"],
                     "disposition": g["disposition"], "excerpts": excerpts})
    return rows


def apply_verdicts(rows, verdicts, questions, gold):
    """verdicts: {qid: {"verdict": keep|fix|drop, "reason": str,
    "query_override": str(可选,仅 fix)}} → v2.1 干净子集。"""
    qmap = {q["id"]: q for q in questions}
    gmap = {g["id"]: g for g in gold}
    keep_q, keep_g, review = [], [], []
    for row in rows:
        v = verdicts.get(row["id"], {})
        decision = v.get("verdict")
        if decision not in ("keep", "fix", "drop"):
            raise ValueError("missing verdict for %s" % row["id"])
        if not v.get("reason"):
            raise ValueError("verdict without reason for %s" % row["id"])
        review.append({"id": row["id"], "verdict": decision, "reason": v["reason"],
                       "query_override": v.get("query_override")})
        if decision == "drop":
            continue
        q = dict(qmap[row["id"]])
        if decision == "fix":
            if not v.get("query_override"):
                raise ValueError("fix without query_override for %s" % row["id"])
            q["query"] = v["query_override"]
        keep_q.append(q)
        keep_g.append(gmap[row["id"]])
    return keep_q, keep_g, review


if __name__ == "__main__":
    if not WS:
        raise SystemExit("DOMIMAP_DEV_CORPUS 未设置：请指向自备语料根目录（见 benchmarks/DATA_LAYOUT.md）")
    pilot = json.load(open(os.path.join(
        ROOT, "out", "diagnostic-runs", "pilot-v2", "pilot-questions.json"),
        encoding="utf-8"))["questions"]
    questions = json.load(open(os.path.join(ROOT, "out", "benchmark",
                                            "dev-questions-v2.json"),
                               encoding="utf-8"))["questions"]
    gold = json.load(open(os.path.join(ROOT, "out", "benchmark", "dev-gold-v2.json"),
                          encoding="utf-8"))["gold"]
    rows = worksheet([p["id"] for p in pilot], questions, gold)
    out = os.path.join(ROOT, "out", "benchmark", "dev-pilot-gold-worksheet.json")
    json.dump(rows, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("worksheet: %d rows → %s" % (len(rows), out))
