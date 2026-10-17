#!/usr/bin/env python3
"""开发集诊断评分：40 题试跑批记录 × dev-gold-v2 的路径级判定与差距归因。

诊断轨口径（非主轨 Accuracy/F1）：正例 Hit@5 = top5 任一映射路径命中 gold 路径；
负例正确 = 空结果拒答。domimap 未命中归因（互斥三选一）：
- ingestion：聚合图节点中无该 gold 文件（摄入缺失）
- recall：图中有但 Searcher top50 无（召回不足）
- ranking：top6..50 命中（排序裁剪失误）
输出 out/diagnostic-runs/pilot-score-v1.json。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "benchmarks"))

PILOT = os.path.join(ROOT, "out", "diagnostic-runs", "pilot-report-v1.json")
QV2 = os.path.join(ROOT, "out", "benchmark", "dev-questions-v2.json")
GV2 = os.path.join(ROOT, "out", "benchmark", "dev-gold-v2.json")
RUNS = os.path.join(ROOT, "out", "diagnostic-runs")
CATEGORIES = ("code_location", "cross_repo_trace", "document_reasoning",
              "knowledge_freshness", "locator_diagnostic", "negative")


def load_records(batch_dir):
    records = []
    rec_dir = os.path.join(batch_dir, "records")
    for name in sorted(os.listdir(rec_dir)):
        system = name.split(".rep")[0]
        with open(os.path.join(rec_dir, name), encoding="utf-8") as stream:
            for line in stream:
                r = json.loads(line)
                r["system"] = system
                records.append(r)
    return records


def hit_at_5(top5, gold_paths):
    gold = set(gold_paths)
    return any(p in gold for p in top5[:5])


def score(records, questions, gold):
    qmap = {q["id"]: q for q in questions}
    gmap = {g["id"]: g for g in gold}
    matrix = {}  # system -> category -> [hit, total] 或负例 [correct, total]
    misses = []
    for r in records:
        q = qmap[r["question_id"]]
        g = gmap[r["question_id"]]
        system, cat = r["system"], q["category"]
        cell = matrix.setdefault(system, {}).setdefault(cat, [0, 0])
        cell[1] += 1
        if cat == "negative":
            correct = not r["top5"]
            if correct:
                cell[0] += 1
            elif system == "domimap":
                misses.append({"id": r["question_id"], "category": cat,
                               "cause": "negative_nonempty", "top5": r["top5"][:3]})
        else:
            if hit_at_5(r["top5"], g["gold_paths"]):
                cell[0] += 1
            elif system == "domimap":
                misses.append({"id": r["question_id"], "category": cat,
                               "gold_paths": g["gold_paths"], "top5": r["top5"]})
    return matrix, misses


def graph_files(graph_path):
    files = set()
    g = json.load(open(graph_path, encoding="utf-8"))
    nodes = g.get("nodes", [])
    if isinstance(nodes, dict):
        nodes = nodes.values()
    for node in nodes:
        f = node.get("file")
        if f:
            files.add(f)
    return files, g


def attribute_misses(misses, graph_path, workspace_root_by_name, top_k=50):
    """domimap miss 归因：ingestion / recall / ranking（互斥）。"""
    sys.path.insert(0, ROOT)
    from domimap.graph import Graph, load_seeds
    from domimap.search import Searcher
    files_in_graph, _ = graph_files(graph_path)
    g = Graph.load(graph_path)
    searcher = Searcher(g)
    seeds = load_seeds(os.path.join(ROOT, "domimap", "seeds.json"))
    qpayload = json.load(open(QV2, encoding="utf-8"))
    text_of = {q["id"]: q["query"] for q in qpayload["questions"]}
    # 反查：图节点 file 为仓内相对路径；gold 为 仓名/相对路径
    fams = sorted(workspace_root_by_name)
    rel_to_fam = {}
    for fam, root in workspace_root_by_name.items():
        for dp, _dn, fnames in os.walk(root):
            for fn in fnames:
                rel = os.path.relpath(os.path.join(dp, fn), root).replace("\\", "/")
                rel_to_fam.setdefault(rel, set()).add(fam)
    for miss in misses:
        if miss["category"] == "negative":
            continue
        golds = miss["gold_paths"]
        in_graph = False
        for gp in golds:
            fam, rel = gp.split("/", 1)
            if rel in files_in_graph and fam in rel_to_fam.get(rel, set()):
                in_graph = True
                break
        if not in_graph:
            miss["attribution"] = "ingestion"
            continue
        result = searcher.query(text_of[miss["id"]], top_k=top_k, expand=False,
                                seeds=seeds)
        ranked = []
        for node in result.get("seeds", [])[:top_k]:
            f = node.get("file", "")
            for fam in rel_to_fam.get(f, fams):
                ranked.append("%s/%s" % (fam, f))
        if any(p in set(golds) for p in ranked[:5]):
            miss["attribution"] = "scoring_mismatch"  # 理论不应发生
        elif any(p in set(golds) for p in ranked):
            miss["attribution"] = "ranking"
            miss["ranked_position"] = next(
                i + 1 for i, p in enumerate(ranked) if p in set(golds))
        else:
            miss["attribution"] = "recall"
    return misses


def main():
    pilot = json.load(open(PILOT, encoding="utf-8"))
    questions = json.load(open(QV2, encoding="utf-8"))["questions"]
    gold = json.load(open(GV2, encoding="utf-8"))["gold"]
    batch_dir = os.path.join(RUNS, "pilot-v1", pilot["batch_40"]["batch_id"])
    records = load_records(batch_dir)
    matrix, misses = score(records, questions, gold)

    workspace = pilot["workspace"]
    ws = os.path.expanduser("~/work/dev-corpus")
    roots = {name: os.path.join(ws, name) for name in workspace}
    graph_path = os.path.join(batch_dir, "artifacts", "domimap", "domimap-idx",
                              "graph.json")
    misses = attribute_misses(misses, graph_path, roots)

    from collections import Counter
    attrib = Counter(m.get("attribution", m["category"]) for m in misses)
    report = {"schema": "domimap.dev-score.v1",
              "batch_id": pilot["batch_40"]["batch_id"],
              "matrix": matrix,
              "domimap_misses": misses,
              "miss_attribution_counts": dict(attrib),
              "note": "诊断轨路径级口径；不用于主轨 Accuracy/F1 或宣称胜出"}
    out = os.path.join(RUNS, "pilot-score-v1.json")
    json.dump(report, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for system in sorted(matrix):
        row = matrix[system]
        cells = ["%s %d/%d" % (c, row.get(c, [0, 0])[0], row.get(c, [0, 0])[1])
                 for c in CATEGORIES if c in row]
        pos = [c for c in CATEGORIES[:4] if c in row]
        hits = sum(row.get(c, [0, 0])[0] for c in pos)
        total = sum(row.get(c, [0, 0])[1] for c in pos)
        print("%-22s 正例Hit@5 %d/%d | %s" % (system, hits, total, " ".join(cells)))
    print("domimap miss 归因:", dict(attrib))
    print("→ %s" % out)


if __name__ == "__main__":
    main()
