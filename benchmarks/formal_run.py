#!/usr/bin/env python3
"""M5.2 正式冻结运行器：五系统 × 问题集（confirm-only 语料）→ 原始记录。

- 记录：每题 top5 候选 + 状态（ok/refused）+ 系统版本 + 运行条件；不判分
  （评分/裁决在 evaluate.py 与独立裁决环节）。
- 种子：domimap/cbm/graphify/codegraph 为确定性系统（seed 不改变行为），
  按 protocol 记录该限制并单次运行；claude-obsidian 适配器为接口边界（未运行）。
"""
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.expanduser("~/work/dm-benchmark")
QF = os.path.join(EXT, "questions.json")
RUNS = os.path.join(EXT, "runs")


def questions():
    return json.load(open(QF, encoding="utf-8"))["questions"]


def write(system, records, meta):
    os.makedirs(RUNS, exist_ok=True)
    p = os.path.join(RUNS, "%s.json" % system)
    json.dump({"system": system, "schema": "domimap.formalrun.v1", "meta": meta,
               "records": records}, open(p, "w"), ensure_ascii=False),


def run_domimap():
    sys.path.insert(0, ROOT)
    from domimap.graph import Graph, load_seeds
    from domimap.search import Searcher
    qs = questions()
    g = Graph.load(os.path.join(ROOT, "out", "confirm-idx", "graph.json"))
    s = Searcher(g)
    seeds = load_seeds(os.path.join(ROOT, "domimap", "seeds.json"))
    t0 = time.time()
    recs = []
    for q in qs:
        r = s.query(q["query"], top_k=5, expand=False, seeds=seeds)
        recs.append({"id": q["id"], "status": "refused" if r.get("refused") else "ok",
                     "top5": [n["file"] for n in r["seeds"][:5]]})
    write("domimap", recs, {"secs": round(time.time() - t0, 1),
                            "seed_note": "确定性系统：seed 不改变行为（protocol 限制记录）",
                            "index": "out/confirm-idx（28 族 confirm-only）"})
    print("domimap done %ds" % (time.time() - t0))




COMP = os.path.expanduser("~/work/yingta/kb-tools-analysis/repos")


def run_cbm():
    """cbm：逐族 index_repository（全量模式），按题路由到族 project 查询。"""
    import re as _re
    import subprocess as _sp
    binary = os.path.join(COMP, "codebase-memory-mcp", "build", "c", "codebase-memory-mcp")
    m = json.load(open(os.path.join(ROOT, "out", "benchmark", "corpus-manifest.json")))
    conf = {r["family"]: r.get("root") or os.path.join(os.path.expanduser(os.environ.get("DOMIMAP_DEV_CORPUS") or ""), r["family"])
            for r in m["families"] if r["split"] == "confirm"}
    proc = _sp.Popen([binary], stdin=_sp.PIPE, stdout=_sp.PIPE,
                     stderr=_sp.DEVNULL, text=True, bufsize=1)
    rid = [0]

    def call(method, params=None, notify=False):
        rid[0] += 1
        msg = {"jsonrpc": "2.0", "method": method}
        if params:
            msg["params"] = params
        if not notify:
            msg["id"] = rid[0]
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()
        if notify:
            return None
        while True:
            line = proc.stdout.readline()
            if not line:
                raise RuntimeError("cbm closed")
            d = json.loads(line)
            if d.get("id") == rid[0]:
                return d.get("result") or d.get("error")

    call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                        "clientInfo": {"name": "dm-formal", "version": "0"}})
    call("notifications/initialized", notify=True)
    fam2proj = {}
    t0 = time.time()
    for fam, root in conf.items():
        r = call("tools/call", {"name": "index_repository", "arguments": {"repo_path": root}})
        fam2proj[fam] = json.loads(r["content"][0]["text"])["project"]
    print("cbm indexed %d families in %ds" % (len(fam2proj), time.time() - t0))
    recs = []
    default_proj = next(iter(fam2proj.values()))
    for q in questions():
        proj = fam2proj.get(q["family"].split("+")[0], default_proj)
        r = call("tools/call", {"name": "search_graph",
                                "arguments": {"query": q["query"], "project": proj}})
        text = ""
        if isinstance(r, dict):
            text = "".join(c.get("text", "") for c in r.get("content", []))
        paths = []
        for mm in _re.findall(r"[\w./-]+\.[A-Za-z]{2,4}", text):
            if mm not in paths:
                paths.append(mm)
        recs.append({"id": q["id"], "status": "ok" if paths else "empty",
                     "top5": paths[:5]})
    write("cbm", recs, {"secs": round(time.time() - t0, 1),
                        "seed_note": "确定性系统；全量模式索引；跨族题路由至首族",
                        "projects": fam2proj})
    proc.stdin.close()
    print("cbm done %ds" % (time.time() - t0))




GF_VENV = open("/tmp/dm-gf-venv.txt").read().strip().split("=", 1)[-1]
CG_BIN = os.path.join(COMP, "codegraph", "dist", "bin", "codegraph.js")


def _family_dirs():
    m = json.load(open(os.path.join(ROOT, "out", "benchmark", "corpus-manifest.json")))
    return {r["family"]: r.get("root") or os.path.join(os.path.expanduser(os.environ.get("DOMIMAP_DEV_CORPUS") or ""), r["family"])
            for r in m["families"] if r["split"] == "confirm"}


def run_graphify():
    """graphify：逐族建图（update），按题路由到族目录查询。"""
    import re as _re
    import subprocess as _sp
    import tempfile as _tf
    import shutil as _sh
    gf = os.path.join(GF_VENV, "bin", "graphify")
    fams = _family_dirs()
    work = _tf.mkdtemp(prefix="dm-formal-gf-")
    t0 = time.time()
    famdir = {}
    for fam, root in fams.items():
        d = os.path.join(work, fam)
        _sh.copytree(root, d, ignore_dangling_symlinks=True)
        _sp.run([gf, "update", "."], cwd=d, check=True, capture_output=True, text=True)
        famdir[fam] = d
    print("graphify indexed %d families in %ds" % (len(famdir), time.time() - t0))
    recs = []
    default = next(iter(famdir.values()))
    for q in questions():
        d = famdir.get(q["family"].split("+")[0], default)
        r = _sp.run([gf, "query", q["query"]], cwd=d, capture_output=True, text=True, timeout=60)
        paths = []
        for mm in _re.findall(r"src=(\S+)", r.stdout):
            p = mm.split("/")[-1] if "/" not in mm else mm
            if p and p not in paths:
                paths.append(p)
        recs.append({"id": q["id"], "status": "ok" if paths else "empty", "top5": paths[:5]})
    write("graphify", recs, {"secs": round(time.time() - t0, 1),
                             "seed_note": "确定性系统；逐族独立图（跨族题路由至首族）"})
    print("graphify done %ds" % (time.time() - t0))


def run_codegraph():
    """codegraph：逐族 init+index，按题路由 explore。"""
    import re as _re
    import subprocess as _sp
    import tempfile as _tf
    import shutil as _sh
    fams = _family_dirs()
    work = _tf.mkdtemp(prefix="dm-formal-cg-")
    t0 = time.time()
    famdir = {}
    for fam, root in fams.items():
        d = os.path.join(work, fam)
        _sh.copytree(root, d, ignore_dangling_symlinks=True)
        _sp.run(["node", CG_BIN, "init"], cwd=d, check=True, capture_output=True, text=True)
        _sp.run(["node", CG_BIN, "index", "."], cwd=d, check=True, capture_output=True, text=True)
        famdir[fam] = d
    print("codegraph indexed %d families in %ds" % (len(famdir), time.time() - t0))
    recs = []
    default = next(iter(famdir.values()))
    for q in questions():
        d = famdir.get(q["family"].split("+")[0], default)
        r = _sp.run(["node", CG_BIN, "explore", q["query"]], cwd=d,
                    capture_output=True, text=True, timeout=60)
        paths = []
        for mm in _re.findall(r"[\w./-]+\.[A-Za-z]{2,4}:\d+", r.stdout):
            p = mm.rsplit(":", 1)[0]
            if os.path.isabs(p):
                p = os.path.relpath(p, d)
            if p not in paths:
                paths.append(p)
        recs.append({"id": q["id"], "status": "ok" if paths else "empty", "top5": paths[:5]})
    write("codegraph", recs, {"secs": round(time.time() - t0, 1),
                              "seed_note": "确定性系统；逐族独立索引（跨族题路由至首族）"})
    print("codegraph done %ds" % (time.time() - t0))




CO_REPO = os.path.join(COMP, "claude-obsidian")


def run_claude_obsidian():
    """claude-obsidian 核心检索直调：setup-retrieve 建 BM25 索引 + retrieve.py 查询。

    其原生形态为宿主技能会话；此处直调其核心检索脚本（BM25-only 确定性，
    不用 ollama rerank），vault=各 confirm 族（wiki 页=族内文本文件）。
    """
    import re as _re
    import shutil as _sh
    import subprocess as _sp
    import tempfile as _tf
    setup = os.path.join(CO_REPO, "scripts", "setup-retrieve.sh")
    retr = os.path.join(CO_REPO, "scripts", "retrieve.py")
    fams = _family_dirs()
    work = _tf.mkdtemp(prefix="dm-formal-co-")
    t0 = time.time()
    famvault = {}
    for fam, root in fams.items():
        vault = os.path.join(work, fam)
        wiki = os.path.join(vault, "wiki", fam)
        os.makedirs(wiki, exist_ok=True)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in
                           {".git", "node_modules", "target", "build", "__pycache__", ".idea"}]
            for fn in filenames:
                src = os.path.join(dirpath, fn)
                rel = os.path.relpath(src, root)
                dst = os.path.join(wiki, rel.replace("/", "__") + ".md")
                try:
                    if os.path.getsize(src) < 400000:
                        _sh.copyfile(src, dst, follow_symlinks=False)
                except OSError:
                    pass
        # 超大族截断：最多保留 800 页（按路径序，确定性），防索引爆炸
        pages = sorted(os.listdir(wiki))
        for extra in pages[800:]:
            os.remove(os.path.join(wiki, extra))
        # 大仓分片建索引：限制每族页数与单页大小，避免 setup-retrieve 超时
        try:
            _sp.run(["bash", setup, "--vault", vault, "--apply"], cwd=CO_REPO,
                    capture_output=True, text=True, timeout=900)
        except Exception:
            pass  # 索引失败的族在查询时表现为空候选（如实记录）
        famvault[fam] = vault
    print("co vaults built %d in %ds" % (len(famvault), time.time() - t0))
    recs = []
    default = next(iter(famvault.values()))
    for q in questions():
        vault = famvault.get(q["family"].split("+")[0], default)
        r = _sp.run(["python3", retr, "--vault", vault, q["query"], "--no-rerank"],
                    capture_output=True, text=True, timeout=120)
        paths = []
        try:
            d = json.loads(r.stdout[r.stdout.index("{"):])
            for c in d.get("candidates", []):
                pp = c.get("page_path", "")
                famname = q["family"].split("+")[0]
                name = os.path.basename(pp)[:-3] if pp.endswith(".md") else os.path.basename(pp)
                # 还原 族__rel（.md 后缀为我们添加）
                name = name.replace("__", "/")
                if name not in paths:
                    paths.append(name)
        except Exception:
            pass
        recs.append({"id": q["id"], "status": "ok" if paths else "empty", "top5": paths[:5]})
    write("claude_obsidian", recs, {"secs": round(time.time() - t0, 1),
                                    "adapter": "核心检索直调（BM25-only 确定性；原生形态为宿主技能会话）",
                                    "seed_note": "确定性（BM25-only）"})
    print("claude_obsidian done %ds" % (time.time() - t0))


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "domimap"
    if which == "domimap":
        run_domimap()
    elif which == "cbm":
        run_cbm()
    elif which == "graphify":
        run_graphify()
    elif which == "codegraph":
        run_codegraph()
    elif which == "claude_obsidian":
        run_claude_obsidian()
