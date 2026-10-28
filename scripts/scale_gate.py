"""合成多仓规模门禁。

每个仓一个 pom 和一个 Java 类。这不是企业 ERP 语料，只检查「仓的数量」本身
会不会让建图或一次查询超出写死的上限。超限退出码 1。
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 合成语料上限。真实 ERP 的体积和延迟要另记，不能拿这次通过代替。
SYNTHETIC_BUDGETS = {
    "build_seconds": 180,
    "graph_bytes": 80_000_000,
    "query_seconds": 3.0,
}


def generate(n, dest):
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    for i in range(n):
        name = "repo-%03d" % i
        base = os.path.join(dest, name)
        os.makedirs(os.path.join(base, "src", "main", "java", "r"))
        dep = ""
        if i:
            dep = ("<dependencies><dependency><groupId>ex</groupId>"
                   "<artifactId>repo-%03d</artifactId></dependency></dependencies>") % (i - 1)
        with open(os.path.join(base, "pom.xml"), "w", encoding="utf-8") as f:
            f.write("<project><groupId>ex</groupId><artifactId>%s</artifactId>%s</project>\n" % (name, dep))
        with open(os.path.join(base, "src", "main", "java", "r", "Svc.java"), "w", encoding="utf-8") as f:
            f.write("package r;\npublic class Svc%03d {\n  public void handle%03d() {}\n}\n" % (i, i))
    return dest


def check(report, budgets):
    violations = []
    if report["build_seconds"] > budgets["build_seconds"]:
        violations.append("build_seconds %s > %s" % (report["build_seconds"], budgets["build_seconds"]))
    if report["graph_bytes"] > budgets["graph_bytes"]:
        violations.append("graph_bytes %s > %s" % (report["graph_bytes"], budgets["graph_bytes"]))
    if report["query_seconds"] > budgets["query_seconds"]:
        violations.append("query_seconds %s > %s" % (report["query_seconds"], budgets["query_seconds"]))
    return violations


def measure(workspace, out_dir, jobs=8):
    from domimap.batch import build_many, discover_roots
    from domimap.graph import Graph
    from domimap.search import Searcher
    roots = discover_roots(workspace)
    t0 = time.perf_counter()
    g, cov, _ = build_many(roots, out_dir, jobs=jobs, force=True)
    build_s = time.perf_counter() - t0
    graph = os.path.join(out_dir, "graph.json")
    t1 = time.perf_counter()
    lazy = Graph.load(graph, lazy_edges=True)
    try:
        Searcher(lazy).query("handle000 订单")
    finally:
        store = getattr(lazy, "_edge_store", None)
        if store is not None:
            store.close()
    query_s = time.perf_counter() - t1
    return {
        "corpus": "synthetic-one-class-per-repo",
        "repos": len(roots),
        "files_scanned": cov["files_scanned"] if cov else 0,
        "nodes": len(g.nodes),
        "edges": len(g.edges),
        "build_seconds": round(build_s, 3),
        "graph_bytes": os.path.getsize(graph),
        "graph_db_bytes": os.path.getsize(os.path.join(out_dir, "graph.db"))
        if os.path.exists(os.path.join(out_dir, "graph.db")) else 0,
        "query_seconds": round(query_s, 3),
    }


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repos", type=int, default=200)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("-o", "--out", default="")
    ap.add_argument("--workspace", default="")
    args = ap.parse_args(argv)
    own = None
    ws = args.workspace
    if not ws:
        own = tempfile.mkdtemp(prefix="dm-scale-src-")
        ws = generate(args.repos, os.path.join(own, "ws"))
    out_dir = tempfile.mkdtemp(prefix="dm-scale-out-")
    try:
        report = measure(ws, out_dir, jobs=args.jobs)
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
        if own:
            shutil.rmtree(own, ignore_errors=True)
    report["budgets"] = SYNTHETIC_BUDGETS
    violations = check(report, SYNTHETIC_BUDGETS)
    report["violations"] = violations
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
