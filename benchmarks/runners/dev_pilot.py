#!/usr/bin/env python3
"""40 题五方诊断轨试跑驱动（测试计划步骤 4 的诊断轨部分）。

流程：从 dev-questions-v2 + dev-gold-v2 选定有界工作区（gold 家族并集，按文件数
取小优先，≤ max_families）→ 分层选 40 题（四类各 8 + locator 4 + negative 4，
题的 gold 家族 ⊆ 工作区）→ run_batch(repeats=[11]) 五系统各一遍 → 另抽 5 题
五重复批次 → 完整性核对（记录数/run_id 唯一/原始工件/预算/错误分类矩阵/env-skip）
→ out/diagnostic-runs/pilot-report-v1.json。

负例（无 gold 字段进入运行器）：选题只输出 id/category/query；运行器侧已有拒收契约。
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "benchmarks"))

from adapters.base import RepoEntry  # noqa: E402
from runners import diagnostic_runner as dr  # noqa: E402

QV2 = os.path.join(ROOT, "out", "benchmark", "dev-questions-v2.json")
GV2 = os.path.join(ROOT, "out", "benchmark", "dev-gold-v2.json")
# 语料根：自备（env；企业私有或开源语料均可，见 benchmarks/DATA_LAYOUT.md）
WS = os.path.expanduser(os.environ.get("DOMIMAP_DEV_CORPUS") or "")
# 文档优先族（逗号分隔；缺省为空——选择器仍可从 gold 族集合里自动挑文档族种子）
DOC_FAMS = set(filter(None, os.environ.get("DOMIMAP_DOC_FAMILIES", "").split(",")))
RUNS = os.path.join(ROOT, "out", "diagnostic-runs")
MAIN4 = ("code_location", "cross_repo_trace", "document_reasoning", "knowledge_freshness")


def family_file_counts():
    if not WS:
        raise SystemExit("DOMIMAP_DEV_CORPUS 未设置：请指向自备语料根目录（见 benchmarks/DATA_LAYOUT.md）")
    counts = {}
    for name in sorted(os.listdir(WS)):
        root = os.path.join(WS, name)
        if os.path.isdir(root) and not name.startswith("."):
            total = 0
            for _dp, _dn, files in os.walk(root):
                total += len(files)
            counts[name] = total
    return counts


def choose_workspace(gold, quotas=None, max_families=8):
    """配额覆盖贪心：文档族种子（无它 doc/freshness 塌陷），每轮加入使配额内
    可选题数增量最大的族（增量同分取文件数小者）；不足则以最小族补满。

    跨仓题的 gold 家族是集合，只按"单族最小"挑会拆散共享表对（曾致 cross=0）。
    """
    quotas = quotas or dict({c: 8 for c in MAIN4}, locator_diagnostic=4, negative=4)
    counts = family_file_counts()
    fams = {f for g in gold for f in g["families"]}

    def selectable(chosen):
        taken, total = {}, 0
        for g in gold:
            if g["families"] and not set(g["families"]) <= chosen:
                continue
            cat = g["category"]
            if taken.get(cat, 0) >= quotas.get(cat, 0):
                continue
            taken[cat] = taken.get(cat, 0) + 1
            total += 1
        return total

    def greedy(seed):
        chosen = set(seed) | (DOC_FAMS & fams)
        while len(chosen) < max_families:
            candidates = fams - chosen
            if not candidates:
                break
            best = min(candidates, key=lambda f: (-selectable(chosen | {f}),
                                                  counts.get(f, 10 ** 9), f))
            if selectable(chosen | {best}) <= selectable(chosen) and len(chosen) >= 6:
                break
            chosen.add(best)
        return chosen

    # 跨仓题的 gold 家族是集合；纯边际增益贪心看不到"差一个成员即完整"的集合
    # （曾致 cross=0）。以每个跨仓 gold 集合为种子跑贪心，取最终可选题最多者。
    seeds = [set(g["families"]) for g in gold
             if g["category"] == "cross_repo_trace" and g["families"]]
    seeds.append(set())  # 无种子基线
    best_ws, best_key = None, None
    for seed in seeds:
        if not seed <= fams:
            continue
        ws = greedy(seed)
        key = (-selectable(ws), sum(counts.get(f, 10 ** 9) for f in ws))
        if best_key is None or key < best_key:
            best_ws, best_key = ws, key
    return best_ws or set(), counts


def select_questions(questions, gold, workspace):
    by_id = {q["id"]: q for q in questions}
    gmap = {g["id"]: g for g in gold}
    picked = []
    quota = {c: 8 for c in MAIN4}
    quota["locator_diagnostic"] = 4
    quota["negative"] = 4
    for g in gold:  # gold 顺序即生成顺序（族序），保证确定性
        q = by_id[g["id"]]
        cat = q["category"]
        if sum(1 for p in picked if p["category"] == cat) >= quota.get(cat, 0):
            continue
        if g["families"] and not set(g["families"]) <= workspace:
            continue
        picked.append({"id": q["id"], "category": cat, "query": q["query"]})
    return picked


def verify_batch(batch_dir, expected_systems, questions, repeats, n_repos=1):
    problems, stats = [], {"error_classes": {}, "secs_total": 0.0, "records": 0}
    # 多仓合并查询的题级预算 = 每仓 query_timeout × 仓数（另留 50% 余量）
    per_question_budget = 90 * max(1, n_repos) * 1.5
    seen_run_ids = set()
    rec_dir = os.path.join(batch_dir, "records")
    for name in sorted(os.listdir(rec_dir)):
        system = name.split(".rep")[0]
        with open(os.path.join(rec_dir, name), encoding="utf-8") as stream:
            for line in stream:
                r = json.loads(line)
                stats["records"] += 1
                stats["secs_total"] += r.get("secs", 0)
                stats["error_classes"][r["error_class"]] = \
                    stats["error_classes"].get(r["error_class"], 0) + 1
                if r["run_id"] in seen_run_ids:
                    problems.append("duplicate run_id %s" % r["run_id"])
                seen_run_ids.add(r["run_id"])
                if not r.get("raw_path") or not os.path.isfile(r["raw_path"]):
                    problems.append("missing raw artifact %s" % r["run_id"])
                if r["question_id"] not in questions:
                    problems.append("unknown question %s" % r["question_id"])
                if r["secs"] > per_question_budget:
                    problems.append("budget overrun %.1fs %s" % (r["secs"], r["run_id"]))
    expected = len(expected_systems) * len(questions) * len(repeats)
    if stats["records"] != expected:
        problems.append("record count %d != expected %d" % (stats["records"], expected))
    return problems, stats


def main():
    qpayload = json.load(open(QV2, encoding="utf-8"))
    gpayload = json.load(open(GV2, encoding="utf-8"))
    questions, gold = qpayload["questions"], gpayload["gold"]
    workspace, counts = choose_workspace(gold)
    pilot = select_questions(questions, gold, workspace)
    cats = {}
    for p in pilot:
        cats[p["category"]] = cats.get(p["category"], 0) + 1
    print("workspace(%d)=%s" % (len(workspace), sorted(workspace)))
    print("pilot=%d by category=%s" % (len(pilot), cats))
    if len(pilot) < 40:
        print("WARNING: pilot fewer than 40 (corpus/coverage limits) — 如实继续")

    pdir = os.path.join(RUNS, "pilot-v1")
    os.makedirs(pdir, exist_ok=True)
    ppath = os.path.join(pdir, "pilot-questions.json")
    json.dump({"questions": pilot}, open(ppath, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    small = pilot[:5]
    spath = os.path.join(pdir, "small5-questions.json")
    json.dump({"questions": small}, open(spath, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    repos = [RepoEntry(name, os.path.join(WS, name)) for name in sorted(workspace)]
    # claude-obsidian 的 contextual 分块走本地 ollama，无页上限时每族 8-15 分钟
    # （实测 7 族无法承受）。试点页上限 300 + prepare 超时 420s；截断逐仓记账不变。
    budget = {"prepare_timeout": 420, "query_timeout": 90, "co_page_cap": 300}
    manifest40 = dr.run_batch(ppath, repos, out_dir=pdir, budget=budget, repeats=[11])
    manifest5 = dr.run_batch(spath, repos, out_dir=pdir, budget=budget,
                             repeats=[11, 23, 37, 53, 71])

    problems40, stats40 = verify_batch(
        os.path.join(pdir, manifest40["batch_id"]),
        manifest40["records_expected"]["systems"], {p["id"] for p in pilot}, [11],
        n_repos=len(repos))
    problems5, stats5 = verify_batch(
        os.path.join(pdir, manifest5["batch_id"]),
        manifest5["records_expected"]["systems"], {p["id"] for p in small},
        [11, 23, 37, 53, 71], n_repos=len(repos))

    report = {"schema": "domimap.pilot-report.v1",
              "workspace": sorted(workspace),
              "workspace_file_counts": {f: counts.get(f) for f in sorted(workspace)},
              "pilot_questions": len(pilot), "pilot_by_category": cats,
              "batch_40": {"batch_id": manifest40["batch_id"],
                           "skipped": manifest40["skipped"], "stats": stats40},
              "batch_5x5": {"batch_id": manifest5["batch_id"],
                            "skipped": manifest5["skipped"], "stats": stats5},
              "integrity_problems": problems40 + problems5,
              "question_file_sha256": hashlib.sha256(
                  open(ppath, "rb").read()).hexdigest()}
    rpath = os.path.join(RUNS, "pilot-report-v1.json")
    json.dump(report, open(rpath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("batch40=%s batch5x5=%s" % (manifest40["batch_id"], manifest5["batch_id"]))
    print("error_classes(40):", stats40["error_classes"])
    print("problems:", len(report["integrity_problems"]))
    print("→ %s" % rpath)


if __name__ == "__main__":
    main()
