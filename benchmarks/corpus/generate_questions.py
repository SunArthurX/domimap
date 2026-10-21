#!/usr/bin/env python3
"""M5.1 confirm 问题集与机械 gold 生成器。

独立性原则：gold 直接从各 confirm 族的**原始文件**经确定性 grep/结构规则派生
（不经 domimap 解析管线）；输出写入仓库外（AGENTS：确认 gold 不进实现目录）。
四类：code_location / cross_repo_trace / document_reasoning / knowledge_freshness。
"""
import json
import os
import re
import sys

# 语料根：自备（企业私有语料或开源语料均可，见 benchmarks/DATA_LAYOUT.md）
WS = os.path.expanduser(os.environ.get("DOMIMAP_DEV_CORPUS") or "")
if not WS:
    raise SystemExit("DOMIMAP_DEV_CORPUS 未设置：请指向自备语料根目录")
EXTERNAL = os.path.expanduser("~/work/dm-benchmark")
MANIFEST = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "out", "benchmark", "corpus-manifest.json")


def scan_family(root):
    ROOT_DIR = root
    """原始事实抽取：mapper 表/路由/类名/文档标题/变更日志条目（grep 级，无产品依赖）。"""
    tables, routes, classes, docs, changelogs, readmes, fresh = {}, {}, [], [], [], [], []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in
                       {".git", "node_modules", "target", "build", "__pycache__", ".idea"}]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, WS)
            try:
                if fn.endswith(".xml") and (fn.endswith("Mapper.xml") or "sqlmap" in dirpath):
                    text = open(p, encoding="utf-8", errors="replace").read()
                    for t in set(re.findall(r"(?:FROM|JOIN|INTO|UPDATE)\s+`?([A-Za-z_][\w]{3,40})`?",
                                            text, re.I)):
                        if not t.upper().startswith(("SELECT", "WHERE", "SET", "VALUES", "DUAL")):
                            tables.setdefault(t, rel)
                elif fn.endswith(".java"):
                    text = open(p, encoding="utf-8", errors="replace").read()
                    for m in re.finditer(r'@(Get|Post|Put|Delete|Request)Mapping\s*\(\s*"([^"]+)"', text):
                        routes.setdefault(m.group(2), rel)
                    cm = re.search(r"(?:class|interface)\s+([A-Z]\w{4,40})\b", text)
                    if cm:
                        classes.append((cm.group(1), rel))
                if fn.upper().startswith("README") and fn.endswith((".md", ".txt")):
                    readmes.append(rel)
                if os.path.getsize(p) < 2000000:
                    try:
                        fresh.append((os.path.getmtime(p), rel))
                    except OSError:
                        pass
                if fn.endswith(".md") and os.path.getsize(p) < 200000:
                    text = open(p, encoding="utf-8", errors="replace").read()[:4000]
                    hm = re.search(r"^#{1,3}\s+(.{4,60})$", text, re.M)
                    if hm:
                        docs.append((hm.group(1).strip(), rel))
                if fn.upper().startswith("CHANGELOG"):
                    changelogs.append(rel)
            except OSError:
                pass
    return {"tables": tables, "routes": routes, "classes": classes,
            "docs": docs, "changelogs": changelogs, "readmes": readmes, "fresh": fresh}


def main():
    manifest = json.load(open(MANIFEST, encoding="utf-8"))
    conf = [r for r in manifest["families"] if r["split"] == "confirm"]
    fams = [r["family"] for r in conf]
    roots = {r["family"]: r.get("root") or os.path.join(WS, r["family"]) for r in conf}
    facts = {f: scan_family(roots[f]) for f in fams}
    DOC_RICH = {"deepseek-harness", "saber-harness", "westpath", "zhiyu"}
    qs = []
    # 1) code_location：表/路由/类 → 定义文件（每族最多 8 题）
    for f, d in facts.items():
        for t, rel in list(d["tables"].items())[:4]:
            qs.append({"family": f, "category": "code_location", "query": t,
                       "gold_paths": [rel], "answerable": True})
        for r, rel in list(d["routes"].items())[:2]:
            qs.append({"family": f, "category": "code_location", "query": r.strip("/") or r,
                       "gold_paths": [rel], "answerable": True})
        for name, rel in d["classes"][:2]:
            qs.append({"family": f, "category": "code_location", "query": name,
                       "gold_paths": [rel], "answerable": True})
    # 2) cross_repo_trace：同名表出现 ≥2 族 → gold=两族定义文件
    by_table = {}
    for f, d in facts.items():
        for t, rel in d["tables"].items():
            by_table.setdefault(t, []).append((f, rel))
    for t, lst in sorted(by_table.items()):
        if len({x[0] for x in lst}) >= 2:
            qs.append({"family": "+".join(sorted({x[0] for x in lst})),
                       "category": "cross_repo_trace", "query": t,
                       "gold_paths": sorted({x[1] for x in lst}), "answerable": True})
    # 3) document_reasoning：文档标题/README → 文档文件（每族至多 6，凑足类配额）
    for f, d in facts.items():
        cap = 16 if f in DOC_RICH else 6
        docs = d["docs"][:cap] or [(f + " README", r) for r in d["changelogs"][:1]]
        for title, rel in docs:
            qs.append({"family": f, "category": "document_reasoning",
                       "query": title, "gold_paths": [rel], "answerable": True})
        # README 兜底：标题抽取失败也以文件名成题
        for rel in d.get("readmes", [])[:2]:
            qs.append({"family": f, "category": "document_reasoning",
                       "query": os.path.basename(rel), "gold_paths": [rel], "answerable": True})
    # 4) knowledge_freshness：文件系统 mtime 的最新文件（机械事实，冻结即清单）
    for f in facts:
        recent = sorted(facts[f]["fresh"], reverse=True)[:3]
        for mt, rel in recent:
            qs.append({"family": f, "category": "knowledge_freshness",
                       "query": "%s 最新 更新 %s" % (f, os.path.basename(rel)),
                       "gold_paths": [rel], "answerable": True})
    # 5) 不可直接回答：真实表名的确定性变形（语料中不存在）→ gold=空
    real_tables = set(by_table)
    rng = __import__("random").Random(20261016)
    made = 0
    for t in sorted(real_tables):
        if made >= 110:
            break
        mut = t[:-2] + "zx" if len(t) > 4 else t + "qx"
        if mut not in real_tables:
            qs.append({"family": "?", "category": "code_location", "query": mut,
                       "gold_paths": [], "answerable": False})
            made += 1
    for i, q in enumerate(qs):
        q["id"] = "cq-%04d" % i
    os.makedirs(EXTERNAL, exist_ok=True)
    out = os.path.join(EXTERNAL, "questions.json")
    json.dump({"schema": "domimap.confirm.v1", "generated": "2026-10-16",
               "generator": "benchmarks/corpus/generate_questions.py（原始文件 grep 派生）",
               "counts": {"answerable": sum(q["answerable"] for q in qs),
                          "unanswerable": sum(not q["answerable"] for q in qs),
                          "families": len(fams)},
               "questions": qs}, open(out, "w"), ensure_ascii=False, indent=1)
    from collections import Counter
    cat = Counter(q["category"] for q in qs if q["answerable"])
    print("answerable=%d unanswerable=%d families=%d" % (
        sum(q["answerable"] for q in qs), sum(not q["answerable"] for q in qs), len(fams)))
    print("by category:", dict(cat), "→", out)


if __name__ == "__main__":
    main()
