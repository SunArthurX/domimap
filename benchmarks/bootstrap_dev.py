#!/usr/bin/env python3
"""M5 DEV 级成对 cluster bootstrap（非 release）：族级重采样 20000 次，hit@5 差值与单侧下界。

正式门槛（evaluate.py --release + 12 项差值 + Bonferroni）需五系统齐与独立裁决；
本脚本输出开发观察统计，输出明确标注 DEV。
"""
import json
import os
import random
import sys

EXT = os.path.expanduser("~/work/dm-benchmark")
ITERS = 20000
SEED = 20261016


def load(name):
    return {r["id"]: r for r in json.load(open(os.path.join(EXT, "runs", "%s.json" % name)))["records"]}


def hit_vector(system, qs):
    out = {}
    for qid, q in qs.items():
        if not q["answerable"]:
            continue
        r = system[qid]
        ok = any(any(gp.endswith("/" + f.split("/")[-1]) or f == gp or
                     f.endswith("/" + gp.split("/")[-1]) for gp in q["gold_paths"])
                 for f in r["top5"])
        out[qid] = 1 if ok else 0
    return out


def main(primary="domimap"):
    qs = {q["id"]: q for q in json.load(open(os.path.join(EXT, "questions.json")))["questions"]}
    fam = {qid: q["family"] for qid, q in qs.items()}
    pv = hit_vector(load(primary), qs)
    clusters = sorted({v for v in fam.values() if v != "?"})
    results = {}
    for baseline in ("cbm", "graphify", "codegraph", "claude_obsidian"):
        bv = hit_vector(load(baseline), qs)
        by_fam = {c: [pv, bv] for c in clusters}
        stats = {c: (sum(pv[i] for i in fam if fam[i] == c and i in pv),
                     sum(1 for i in fam if fam[i] == c and i in pv),
                     sum(bv[i] for i in fam if fam[i] == c and i in bv)) for c in clusters}
        rng = random.Random(SEED)
        diffs = []
        for _ in range(ITERS):
            ps = bs = ns = 0
            for c in (rng.choice(clusters) for _ in clusters):
                p, n, b = stats[c]
                ps += p; bs += b; ns += n
            diffs.append((ps - bs) / ns if ns else 0.0)
        diffs.sort()
        lo = diffs[int(0.05 * ITERS)]  # 单侧 95% 下界（DEV 级；正式用 Bonferroni/12）
        point = sum(pv.values()) / len(pv) - sum(bv.values()) / len(bv)
        results[baseline] = {"point_diff": round(point, 4),
                             "lower_bound_95_one_sided": round(lo, 4),
                             "bootstrap_iters": ITERS, "clusters": len(clusters)}
        print("%s vs %s: 点差 %.1fpp, 单侧95%%下界 %.1fpp (%d 次, %d 族)" %
              (primary, baseline, 100 * point, 100 * lo, ITERS, len(clusters)))
    json.dump({"grade": "DEV（非 release：单指标 hit@5，无独立裁决，无多重校正）",
               "primary": primary, "results": results},
              open("out/verification/m5-bootstrap-dev.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
