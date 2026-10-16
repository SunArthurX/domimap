#!/usr/bin/env python3
"""tiny dev 五系统回放 spike（M0.2）：同语料同题，适配器 → 公共输出映射 → Hit@5。

用法：
  python3 -B benchmarks/tiny_dev/runner.py --system domimap
  python3 -B benchmarks/tiny_dev/runner.py --system graphify
  python3 -B benchmarks/tiny_dev/runner.py --selfcheck     # 评分器契约自检（负面：>5 不补分/缺 gold 拒绝）

只做开发观察，不产生正式比较结论（specs/benchmark.md 的正式门槛在 M5 冻结批次执行）。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
COMP = os.path.expanduser("~/work/yingta/kb-tools-analysis/repos")

QUESTIONS = json.load(open(os.path.join(HERE, "questions.json"), encoding="utf-8"))["questions"]


def norm_path(p, corpus_root):
    """各系统路径形式 → 语料相对路径（canonical 映射登记点）。"""
    p = p.replace("\\", "/")
    marker = "mini/"
    i = p.find(marker)
    rel = p[i + len(marker):] if i >= 0 else os.path.relpath(p, corpus_root)
    return rel.lstrip("./")


def hit_at_5(candidates, gold):
    """前 5 主证据位置命中任一 gold 即 1；第 6+ 不补分（与正式口径一致）。"""
    for c in candidates[:5]:
        if any(g == c["path"] or c["path"].endswith(g) for g in gold):
            return 1
    return 0


# ---------------- domimap 适配器（原生 CLI） ----------------
def run_domimap(corpus, out):
    subprocess.run([sys.executable, "-B", "-m", "domimap", "build", corpus, "-o", out],
                   cwd=ROOT, check=True, capture_output=True)
    results = []
    for q in QUESTIONS:
        r = subprocess.run([sys.executable, "-B", "-m", "domimap", "query", q["query"],
                            "-g", os.path.join(out, "mini", "graph.json")],
                           cwd=ROOT, capture_output=True, text=True)
        # Read 等价输出：@路径 行
        paths = [norm_path(m, corpus) for m in re.findall(r"@\s*(\S+)", r.stdout)]
        dedup = []
        for p in paths:
            if p not in dedup:
                dedup.append(p)
        results.append({"question_id": q["id"],
                        "candidates": [{"path": p} for p in dedup[:10]]})
    return results


# ---------------- graphify 适配器（原生 CLI） ----------------
def graphify_venv():
    env = os.environ.get("DM_GF_VENV")
    if env:
        return os.path.join(env, "bin", "graphify")
    raise SystemExit("graphify 适配器需 DM_GF_VENV=<venv>（pip install <克隆> 的一次性环境）")


def run_graphify(corpus, out):
    gf = graphify_venv()
    work = tempfile.mkdtemp(prefix="dm-tiny-gf-")
    shutil.copytree(corpus, os.path.join(work, "mini"))
    subprocess.run([gf, "update", "."], cwd=os.path.join(work, "mini"),
                   check=True, capture_output=True, text=True)
    results = []
    for q in QUESTIONS:
        r = subprocess.run([gf, "query", q["query"]], cwd=os.path.join(work, "mini"),
                           capture_output=True, text=True)
        paths = [norm_path("mini/" + m, corpus) for m in re.findall(r"src=(\S+)", r.stdout)]
        dedup = []
        for p in paths:
            if p and p not in dedup:
                dedup.append(p)
        results.append({"question_id": q["id"],
                        "candidates": [{"path": p} for p in dedup[:10]]})
    return results


# ---------------- codegraph 适配器（原生 CLI：init/index/explore） ----------------
def run_codegraph(corpus, out):
    import glob as _glob
    cands = _glob.glob(os.path.join(COMP, "codegraph", "dist", "bin", "codegraph.js"))
    if not cands:
        raise SystemExit("codegraph dist 未构建（make: npm run build）")
    cg = cands[0]
    work = tempfile.mkdtemp(prefix="dm-tiny-cg-")
    shutil.copytree(corpus, os.path.join(work, "mini"))
    wmini = os.path.join(work, "mini")
    for args in (["init"], ["index", "."]):
        subprocess.run(["node", cg] + args, cwd=wmini, check=True, capture_output=True, text=True)
    results = []
    for q in QUESTIONS:
        r = subprocess.run(["node", cg, "explore", q["query"]], cwd=wmini,
                           capture_output=True, text=True)
        paths = []
        for m in re.findall(r"[\(\[]([\w./-]+\.[a-z]{2,4}):\d+", r.stdout):
            p = m if not os.path.isabs(m) else os.path.relpath(m, wmini)
            if p not in paths:
                paths.append(p)
        results.append({"question_id": q["id"], "candidates": [{"path": p} for p in paths[:10]]})
    return results


ADAPTERS = {"domimap": run_domimap, "graphify": run_graphify, "codegraph": run_codegraph}


def selfcheck():
    gold = ["a.py"]
    assert hit_at_5([{"path": "a.py"}] * 5, gold) == 1
    assert hit_at_5([{"path": "x"}] * 5 + [{"path": "a.py"}], gold) == 0, "第 6 命中不得补分"
    assert hit_at_5([], gold) == 0
    print("[selfcheck] Hit@5 契约 OK（>5 不补分/空候选零分）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", choices=sorted(ADAPTERS))
    ap.add_argument("--corpus", default=os.path.join(ROOT, "tests", "fixtures", "mini"))
    ap.add_argument("--selfcheck", action="store_true")
    a = ap.parse_args()
    if a.selfcheck:
        selfcheck()
        return
    out = tempfile.mkdtemp(prefix="dm-tiny-%s-" % a.system)
    results = ADAPTERS[a.system](a.corpus, out)
    hits, rows = 0, []
    for r, q in zip(results, QUESTIONS):
        h = hit_at_5(r["candidates"], q["gold_paths"])
        hits += h
        rows.append({"id": q["id"], "hit": h,
                     "top5": [c["path"] for c in r["candidates"][:5]]})
    print(json.dumps({"system": a.system, "hit_at_5": "%d/%d" % (hits, len(QUESTIONS)),
                      "detail": rows}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
