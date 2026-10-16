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

def scan_many(roots, jobs=8):
    """并行扫描多仓并合并 records（服务名带仓前缀，跨仓 RPC/表引用自然对齐）。"""
    merged = {"services": {}, "classes": [], "methods": [], "routes": [], "rpc": [],
              "topics": [], "sqlstmts": [], "tables": [], "pages": [], "docs": [], "entities": [],
              "calls": [],
              "coverage": {"files_scanned": 0, "skipped": []}}
    def one(root):
        label = os.path.basename(os.path.abspath(root))
        return lite_scan.scan_repo(root, repo_label=label)
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        for R in ex.map(one, roots):
            for k in ("classes", "methods", "routes", "rpc", "topics", "sqlstmts", "tables", "pages", "docs", "entities", "calls"):
                merged[k].extend(R[k])
            merged["services"].update(R["services"])
            merged["coverage"]["files_scanned"] += R["coverage"]["files_scanned"]
            merged["coverage"]["skipped"].extend(R["coverage"]["skipped"])
    return merged

def build_many(roots, out_dir, jobs=8, force=False, merged_name=None):
    """多仓构建：合并全局图 + 每仓 manifest（供 update 增量）。"""
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
        g.save(os.path.join(out_dir, "graph.json"))
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
