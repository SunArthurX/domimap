"""batch — 多仓发现、并行批量构建、跨仓合并图、仓级增量更新。

增量策略（MVP，仓级粒度）：manifest 记录每个文件的 (mtime_ns, size) 签名；
update 时 stat 重扫比对——签名不变即 no-op（毫秒级），变化则整仓重建（实测 0.1-1s/仓）。
文件级增量待 graphify AST 引擎切换后按内容哈希做。
"""
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor

from . import lite_scan
from .graph import Graph, load_seeds

def discover_roots(base):
    """发现子仓：含 pom.xml / build.gradle / .git / package.json 的一级（含一层嵌套）目录。"""
    roots = []
    for name in sorted(os.listdir(base)):
        p = os.path.join(base, name)
        if not os.path.isdir(p) or name.startswith(".") or name in lite_scan.SKIP_DIRS:
            continue
        if any(os.path.exists(os.path.join(p, m)) for m in ("pom.xml", "build.gradle", ".git", "package.json")):
            roots.append(p)
            continue
        # 一层嵌套（如聚合工程下按模块成仓）
        for sub in sorted(os.listdir(p)):
            q = os.path.join(p, sub)
            if os.path.isdir(q) and any(os.path.exists(os.path.join(q, m))
                                        for m in ("pom.xml", "build.gradle", ".git")):
                roots.append(q)
    return roots

def repo_signature(root):
    sig = {}
    for path, rel in lite_scan._walk(root):
        try:
            st = os.stat(path)
        except OSError:
            continue
        sig[rel] = [st.st_mtime_ns, st.st_size]
    return sig

def repo_changed(root, manifest_path):
    from . import __version__
    if not os.path.exists(manifest_path):
        return True
    try:
        with open(manifest_path, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("tool_version") != __version__:
            return True  # 代码升级（synthesizer 规则变化）→ 整仓重建
        old = d.get("files", {})
    except (OSError, json.JSONDecodeError):
        return True
    return repo_signature(root) != old

def normalized(g):
    """规范化等价视图（增量=全量收敛比较用）：(节点ID集, 规范化边五元组集)。"""
    return (frozenset(g.nodes),
            frozenset((e["src"], e["dst"], e["kind"], e["conf"], e["prov"]) for e in g.edges))


def _seeds_digest(path):
    import hashlib
    return hashlib.sha256(open(path, "rb").read()).hexdigest()

def _publish(out_dir, g, roots):
    """发布协议：捕获来源字节→发布不可变代→指针切换成功后复制 graph.json（兼容旧 CLI）。"""
    import shutil as _sh
    from .store import EvidenceStore
    store = EvidenceStore(os.path.join(out_dir, "store.db"))
    for root in roots:
        label = os.path.basename(os.path.abspath(root))
        for path, rel in lite_scan._walk(root):
            try:
                store.capture_source(label, label + "|" + rel, path, rel)
            except (OSError, ValueError):
                continue
    rec = store.publish_graph(g)
    store.set_seeds_digest(_seeds_digest(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "seeds.json")))
    _sh.copyfile(rec["path"], os.path.join(out_dir, "graph.json"))
    store.close()
    return rec

def _store_healthy(out_dir):
    from .store import EvidenceStore
    db = os.path.join(out_dir, "store.db")
    if not os.path.exists(db):
        return False
    store = EvidenceStore(db)
    try:
        ok = store.active_generation() is not None and store.seeds_digest() == _seeds_digest(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "seeds.json"))
        return ok
    finally:
        store.close()

def build_many(roots, out_dir, jobs=8, force=False, merged_name=None):
    """多仓构建：合并全局图 + 每仓 manifest（供 update 增量）。

    no-op 条件（D1 修复）：全部仓 manifest 未变 且 active generation 完整 且 seeds 摘要一致；
    图丢失/损坏/种子变化 → 重建，不误报 no-op。
    """
    seeds = load_seeds(os.path.join(os.path.dirname(os.path.abspath(__file__)), "seeds.json"))
    manifests = {}
    results = []
    for root in roots:
        label = os.path.basename(os.path.abspath(root))
        mdir = os.path.join(out_dir, label)
        mpath = os.path.join(mdir, "manifest.json")
        if not force and not repo_changed(root, mpath):
            results.append((label, "no-op"))
            manifests[label] = mpath
            continue
        manifests[label] = mpath
        results.append((label, "rebuild"))
    dirty = [r for r, st in results if st == "rebuild"]
    if not dirty and not _store_healthy(out_dir):
        dirty = list(roots)  # D1：manifest 未变但 active 代丢失/损坏或 seeds 变化 → 全量重建
        results = [(os.path.basename(os.path.abspath(r)), "rebuild") for r in roots]
    if dirty:
        Rs = {}
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            for root, R in zip(dirty, ex.map(lambda r: lite_scan.scan_repo(
                    r, repo_label=os.path.basename(os.path.abspath(r))), dirty)):
                Rs[root] = R
        merged = {"services": {}, "classes": [], "methods": [], "routes": [], "rpc": [],
                  "topics": [], "sqlstmts": [], "tables": [], "pages": [], "docs": [], "entities": [],
                  "calls": [],
                  "coverage": {"files_scanned": 0, "skipped": []}}
        # 已有 no-op 仓复用上次 records？MVP：全量重扫（秒级），只写变更仓 manifest
        for root in roots:
            label = os.path.basename(os.path.abspath(root))
            R = Rs.get(root) or lite_scan.scan_repo(root, repo_label=label)
            for k in ("classes", "methods", "routes", "rpc", "topics", "sqlstmts", "tables", "pages", "docs", "entities", "calls"):
                merged[k].extend(R[k])
            merged["services"].update(R["services"])
            merged["coverage"]["files_scanned"] += R["coverage"]["files_scanned"]
            merged["coverage"]["skipped"].extend(R["coverage"]["skipped"])
            mdir = os.path.join(out_dir, label)
            os.makedirs(mdir, exist_ok=True)
            with open(os.path.join(mdir, "manifest.json"), "w", encoding="utf-8") as f:
                from . import __version__ as _v
                json.dump({"root": os.path.abspath(root), "tool_version": _v,
                           "files": repo_signature(root)}, f, ensure_ascii=False)
        g = Graph()
        g.build_from_records(merged, seeds)
        name = merged_name or os.path.basename(os.path.abspath(out_dir)) or "merged"
        os.makedirs(out_dir, exist_ok=True)
        _publish(out_dir, g, roots)
        with open(os.path.join(out_dir, "coverage.json"), "w", encoding="utf-8") as f:
            json.dump(merged["coverage"], f, ensure_ascii=False, indent=1)
        return g, merged["coverage"], results
    return None, None, results

def update(out_dir, jobs=8):
    """按 manifest 增量：no-op 仓跳过，变更仓重建合并图。"""
    roots = []
    for name in sorted(os.listdir(out_dir)):
        mp = os.path.join(out_dir, name, "manifest.json")
        if os.path.exists(mp):
            try:
                with open(mp, encoding="utf-8") as f:
                    roots.append(json.load(f)["root"])
            except (OSError, json.JSONDecodeError):
                pass
    if not roots:
        return None, None, []
    return build_many(roots, out_dir, jobs=jobs, merged_name=os.path.basename(os.path.abspath(out_dir)))
