#!/usr/bin/env python3
"""M5.2 事实级 gold（外部）：每题必要事实 = 陈述 + 源文件 + 行号跨度。

机械派生（grep 首现行号），与 questions.json 同源同规则；输出仅入
~/work/dm-benchmark/fact-gold.json（实现目录外）。独立盲化裁决另行进行
（本文件是裁决输入，不是裁决本身——见 handoff 阻塞记录）。
"""
import json
import os
import re

# 语料根：自备（企业私有语料或开源语料均可，见 benchmarks/DATA_LAYOUT.md）
WS = os.path.expanduser(os.environ.get("DOMIMAP_DEV_CORPUS") or "")
if not WS:
    raise SystemExit("DOMIMAP_DEV_CORPUS 未设置：请指向自备语料根目录")
EXT = os.path.expanduser("~/work/dm-benchmark")
MAN = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "out", "benchmark", "corpus-manifest.json")


def locate(root, rel, needle):
    """needle 在文件中的首现行号（1 基）；未命中返回 None。"""
    p = os.path.join(root, rel)
    try:
        for i, line in enumerate(open(p, encoding="utf-8", errors="replace"), 1):
            if needle in line:
                return i
    except OSError:
        pass
    return None


def main():
    qs = json.load(open(os.path.join(EXT, "questions.json"), encoding="utf-8"))
    m = json.load(open(MAN, encoding="utf-8"))
    roots = {r["family"]: r.get("root") or os.path.join(WS, r["family"])
             for r in m["families"]}
    facts = []
    for q in qs["questions"]:
        if not q["answerable"]:
            facts.append({"id": q["id"], "answerable": False,
                          "necessary_facts": [], "correct_behavior": "拒答（不编造）"})
            continue
        nfs = []
        for gp in q["gold_paths"]:
            fam = gp.split("/", 1)[0]
            root = roots.get(fam, WS)
            line = locate(root, gp, q["query"].split()[0] if q["query"] else q["query"])
            nf = {"statement": "「%s」的定义/依据位于 %s" % (q["query"], gp),
                  "source_path": gp}
            if line:
                nf["line"] = line
            nfs.append(nf)
        facts.append({"id": q["id"], "answerable": True, "necessary_facts": nfs,
                      "correct_behavior": "给出可核验源位置"})
    out = {"schema": "domimap.factgold.v1", "generated": "2026-10-16",
           "adjudication": "机械派生草稿；独立盲化裁决未执行（正式门槛阻塞项）",
           "facts": facts}
    json.dump(out, open(os.path.join(EXT, "fact-gold.json"), "w"), ensure_ascii=False, indent=1)
    ok = sum(1 for f in facts if f["answerable"])
    with_line = sum(1 for f in facts if f["answerable"] and
                    any("line" in n for n in f["necessary_facts"]))
    print("fact-gold: %d 可回答（含行号 %d）/ %d 不可回答 → %s" %
          (ok, with_line, len(facts) - ok, os.path.join(EXT, "fact-gold.json")))


if __name__ == "__main__":
    main()
