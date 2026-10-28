#!/usr/bin/env python3
"""AC-R12-02 消融重跑（RV06 诚实化后补做）：当前源码、同题集、同预算的三配置对照。

配置（单次确定性，同一冻结 dev 集 out/benchmark/dev-gold-v2.1.json 的 33 题）：
  text_only              不挂 knowledge、禁用图扩展（expand=False）——纯文本泳道
  text_plus_graph        挂 knowledge、图扩展关闭与否按默认（expand=True）——文本+图
  text_graph_knowledge   同上 + 人工知识挂接（knowledge.db 存在时 attach）

口径（诊断轨，非主轨 Accuracy/F1）：正例 Hit@5 = top5 任一路径命中 gold 路径；负例正确 = 拒答。
输出逐题结果 + 分层（类别）汇总，绑定源码指纹/输入哈希/命令，供 progress 证据引用。

用法：python3 -B benchmarks/runners/ablation_local.py -g <graph.json> [-o out/verification/...]
"""
import argparse
import hashlib
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

GV21 = os.path.join(ROOT, "out", "benchmark", "dev-gold-v2.1.json")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def run_config(name, gold, graph_path, attach_knowledge, expand):
    from domimap.graph import Graph, load_seeds
    from domimap.search import Searcher
    seeds = load_seeds(os.path.join(ROOT, "domimap", "seeds.json"))
    g = Graph.load(graph_path)
    s = Searcher(g, cache_path=None)
    knowledge_attached = False
    if attach_knowledge:
        from domimap.knowledge import attach_if_present
        knowledge_attached = attach_if_present(s, graph_path)
    rows = []
    for item in gold:
        t0 = time.time()
        r = s.query(item["query"], top_k=5, expand=expand, seeds=seeds)
        files = []
        for n in r["seeds"]:
            f = n.get("file")
            if f and f not in files:
                files.append(f)
        top5 = files[:5]
        if item["category"] == "negative":
            correct = bool(r.get("refused")) or not top5
            hit = None
        else:
            correct = None
            gset = set(item["gold_paths"])
            hit = any(p in gset or any(p.endswith(x) or x.endswith(p) for x in gset)
                      for p in top5)
        rows.append({"id": item["id"], "category": item["category"], "hit": hit,
                     "correct_negative": correct, "secs": round(time.time() - t0, 2),
                     "top5": top5[:3]})
    pos = [r for r in rows if r["hit"] is not None]
    neg = [r for r in rows if r["correct_negative"] is not None]
    by_cat = {}
    for r in pos:
        c = by_cat.setdefault(r["category"], [0, 0])
        c[1] += 1
        c[0] += 1 if r["hit"] else 0
    summary = {
        "hit_at_5": round(sum(1 for r in pos if r["hit"]) / len(pos), 4) if pos else None,
        "positives": len(pos),
        "negative_correct": round(sum(1 for r in neg if r["correct_negative"]) / len(neg), 4) if neg else None,
        "negatives": len(neg),
        "knowledge_attached": knowledge_attached,
        "by_category": {k: "%d/%d" % tuple(v) for k, v in sorted(by_cat.items())},
    }
    return {"config": name, "attach_knowledge": attach_knowledge, "expand": expand,
            "summary": summary, "rows": rows}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-g", "--graph", required=True)
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args()

    gold_doc = json.load(open(GV21, encoding="utf-8"))
    gold = gold_doc["gold"]
    # gold 只带 id/gold_paths；query 文本在 dev-questions-v2（同 id 关联）
    qdoc = json.load(open(os.path.join(ROOT, "out", "benchmark", "dev-questions-v2.json"),
                          encoding="utf-8"))
    qtext = {q["id"]: q["query"] for q in qdoc["questions"]}
    for item in gold:
        item["query"] = qtext[item["id"]]  # 缺题即 KeyError（如实失败，不静默跳题）
    configs = [
        ("text_only", False, False),
        ("text_plus_graph", False, True),
        ("text_graph_knowledge", True, True),
    ]
    results = {}
    for name, attach, expand in configs:
        t0 = time.time()
        results[name] = run_config(name, gold, args.graph, attach, expand)
        results[name]["wall_secs"] = round(time.time() - t0, 1)
        sm = results[name]["summary"]
        print("[ablation] %-22s Hit@5=%s (%d 正例)  负例正确=%s  knowledge=%s  %.0fs" % (
            name, sm["hit_at_5"], sm["positives"], sm["negative_correct"],
            sm["knowledge_attached"], results[name]["wall_secs"]))

    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import check_specs
    doc = {
        "schema": "domimap.ablation.v2",
        "grade": "DEV 消融重跑（同题集 dev-gold-v2.1 33 题 / 同预算 top_k=5 / 单次确定性 / 当前源码）",
        "source_fingerprint": check_specs.source_fingerprint(),
        "inputs": {"graph": args.graph, "graph_sha256": sha(args.graph),
                   "gold": GV21, "gold_sha256": sha(GV21)},
        "command": [sys.executable, "-B", "benchmarks/runners/ablation_local.py",
                    "-g", args.graph, "-o", args.out],
        "generated": time.time(),
        "results": {k: v["summary"] for k, v in results.items()},
        "detail": {k: v["rows"] for k, v in results.items()},
        "limitations": [
            "诊断轨口径（路径级 Hit@5/拒答正确），非主轨 Accuracy/F1；结论仅适用本 dev 集与本图。",
            "knowledge 配置挂接的是图旁 knowledge.db 当前内容（本跑为空库时 knowledge_attached=false，如实记录）。",
        ],
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    os.replace(tmp, args.out)
    print("[ablation] → %s" % args.out)


if __name__ == "__main__":
    main()
