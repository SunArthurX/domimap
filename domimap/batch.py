"""batch — 多仓发现、并行批量构建、跨仓合并图、仓级增量更新。

增量策略（仓级粒度）：manifest 记录每个文件的内容 sha256（D12：mtime/size 不是内容版本，
cp -p / touch -r 后的同尺寸改写也能识别）；update 重算哈希比对——不变即 no-op，变化则整仓重建。
派生产物（graph.json/coverage.json/manifest.json）一律 tmp+fsync+rename 原子落盘；
兼容副本 graph.json 的内容哈希须等于 active 代，否则视为不健康并重发布。
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
    """文件 → 内容 sha256（与扫描期 capture 回调计算的签名同源同集合）。"""
    sig = {}
    for path, rel in lite_scan._walk(root):
        try:
            with open(path, "rb") as f:
                sig[rel] = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            continue
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

def _label_of(root):
    return os.path.basename(os.path.abspath(root))


def _unique_labels(roots):
    """每个来源根一个稳定标签：默认目录名；同名时追加绝对路径摘要（仅冲突者），不让后写者覆盖身份（D11）。"""
    base = {r: _label_of(r) for r in roots}
    counts = {}
    for l in base.values():
        counts[l] = counts.get(l, 0) + 1
    out = {}
    for r, l in base.items():
        if counts[l] > 1:
            l = "%s~%s" % (l, hashlib.sha256(os.path.abspath(r).encode("utf-8")).hexdigest()[:6])
        out[r] = l
    return out


RECORD_LISTS = ("classes", "methods", "routes", "rpc", "topics", "sqlstmts", "tables", "pages", "docs", "entities")


def _stamp_sid(R, label, first_seen=None):
    """把来源身份 label|rel 戳到每条记录上，供图节点 meta.sid 与证据解析使用；
    文档记录另带内容首次收录时间（content_first_seen），供无正文纪元时作为资格/时效依据（F4）。"""
    for key in RECORD_LISTS:
        for rec in R.get(key, []):
            rel = rec.get("file") or rec.get("path")
            if rel:
                rec["sid"] = label + "|" + rel
    if first_seen:
        for d in R.get("docs", []):
            fs = first_seen.get(d.get("path"))
            if fs:
                d["content_first_seen"] = fs
    return R


def _atomic_write(path, data):
    """tmp → fsync → rename → 目录 fsync：读者只会看到完整的旧文件或完整的新文件（D12）。"""
    from .storage import sync_directory
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    sync_directory(os.path.dirname(os.path.abspath(path)))


def _capture_into(store, label, signature, first_seen=None):
    """扫描回调：同一份字节既固化为证据（D10），也产出 manifest 的内容签名（D12），不再二次读盘。

    first_seen[rel] 记录该内容的首次收录时间（store 按内容 sha 取 min）：复制/touch 不刷新（F4）。
    """
    def capture(path, rel, raw):
        signature[rel] = hashlib.sha256(raw).hexdigest()
        rec = store.capture_source(label, label + "|" + rel, path, rel, raw=raw)
        if first_seen is not None:
            first_seen[rel] = rec["first_seen"]
    return capture


def publish_generation(store, g, out_dir):
    """发布协议：不可变代 → seeds 摘要 → 指针切换成功后原子落盘 graph.json 兼容副本（字节等于该代）。"""
    rec = store.publish_graph(g)
    store.set_seeds_digest(_seeds_digest(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "seeds.json")))
    with open(rec["path"], "rb") as f:
        _atomic_write(os.path.join(out_dir, "graph.json"), f.read())
    return rec

def _store_healthy(out_dir):
    from .store import EvidenceStore
    db = os.path.join(out_dir, "store.db")
    if not os.path.exists(db):
        return False
    store = EvidenceStore(db)
    try:
        active = store.active_generation()
        if active is None or store.seeds_digest() != _seeds_digest(
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "seeds.json")):
            return False
        # 兼容副本是所有入口实际读取的文件：缺失/截断/篡改都不是"无变更"（D1 残留、D12）
        compat = os.path.join(out_dir, "graph.json")
        try:
            with open(compat, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest() == active["sha256"]
        except OSError:
            return False
    finally:
        store.close()

def build_many(roots, out_dir, jobs=8, force=False, merged_name=None, service_prefixes=None, labels=None):
    """多仓构建：合并全局图 + 每仓 manifest（供 update 增量）。所有 build 入口共用此证据契约。

    labels: {root: label} 显式标签（update/rebind 自 manifest 读回，保证身份稳定）；缺省按目录名，
    同名仓自动追加路径摘要（D11）。
    service_prefixes: {root: prefix | None}。None = 该仓服务不加前缀（单仓 build 的既有命名）；
    缺省为该仓标签（多仓发现模式的既有命名）。两者都写入 manifest，update 沿用。
    no-op 条件（D1 修复）：全部仓 manifest 未变 且 active generation 完整 且 seeds 摘要一致；
    图丢失/损坏/种子变化 → 重建，不误报 no-op。
    """
    from .store import EvidenceStore
    seeds = load_seeds(os.path.join(os.path.dirname(os.path.abspath(__file__)), "seeds.json"))
    auto = _unique_labels(roots)
    labels = dict(labels or {})
    service_prefixes = dict(service_prefixes or {})

    def _lookup(table, root, default):
        if root in table:
            return table[root]
        return table.get(os.path.abspath(root), default)

    def label_of(root):
        return _lookup(labels, root, auto[root])

    def prefix_of(root):
        return _lookup(service_prefixes, root, label_of(root))

    results = []
    for root in roots:
        label = label_of(root)
        mpath = os.path.join(out_dir, label, "manifest.json")
        if not force and not repo_changed(root, mpath):
            results.append((label, "no-op"))
            continue
        results.append((label, "rebuild"))
    dirty = [r for r, (_, st) in zip(roots, results) if st == "rebuild"]
    if not dirty and not _store_healthy(out_dir):
        dirty = list(roots)  # D1：manifest 未变但 active 代丢失/损坏或 seeds 变化 → 全量重建
        results = [(label_of(r), "rebuild") for r in roots]
    if not dirty:
        return None, None, results
    os.makedirs(out_dir, exist_ok=True)
    store = EvidenceStore(os.path.join(out_dir, "store.db"))
    try:
        signatures = {}

        def scan(root):
            label = label_of(root)
            sig = signatures.setdefault(root, {})
            seen = {}
            R = lite_scan.scan_repo(root, repo_label=prefix_of(root),
                                    capture=_capture_into(store, label, sig, seen))
            return _stamp_sid(R, label, seen)
        Rs = {}
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            for root, R in zip(dirty, ex.map(scan, dirty)):
                Rs[root] = R
        merged = {"services": {}, "classes": [], "methods": [], "routes": [], "rpc": [],
                  "topics": [], "sqlstmts": [], "tables": [], "pages": [], "docs": [], "entities": [],
                  "calls": [],
                  "coverage": {"files_scanned": 0, "skipped": []}}
        # 已有 no-op 仓复用上次 records？MVP：全量重扫（秒级），只写变更仓 manifest
        for root in roots:
            label = label_of(root)
            R = Rs.get(root) or scan(root)
            for k in ("classes", "methods", "routes", "rpc", "topics", "sqlstmts", "tables", "pages", "docs", "entities", "calls"):
                merged[k].extend(R[k])
            merged["services"].update(R["services"])
            merged["coverage"]["files_scanned"] += R["coverage"]["files_scanned"]
            merged["coverage"]["skipped"].extend(R["coverage"]["skipped"])
            mdir = os.path.join(out_dir, label)
            os.makedirs(mdir, exist_ok=True)
            from . import __version__ as _v
            manifest = {"root": os.path.abspath(root), "label": label, "tool_version": _v,
                        "service_prefix": prefix_of(root),
                        "files": signatures.get(root) or repo_signature(root)}
            _atomic_write(os.path.join(mdir, "manifest.json"),
                          json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
        g = Graph()
        g.build_from_records(merged, seeds)
        publish_generation(store, g, out_dir)
    finally:
        store.close()
    _atomic_write(os.path.join(out_dir, "coverage.json"),
                  json.dumps(merged["coverage"], ensure_ascii=False, indent=1).encode("utf-8"))
    return g, merged["coverage"], results

def _read_manifests(out_dir):
    """工作区登记的来源：label → manifest 内容（manifest 即持久化的来源登记）。"""
    found = {}
    for name in sorted(os.listdir(out_dir)):
        mp = os.path.join(out_dir, name, "manifest.json")
        if not os.path.exists(mp):
            continue
        try:
            with open(mp, encoding="utf-8") as f:
                d = json.load(f)
            d["root"]
        except (OSError, json.JSONDecodeError, KeyError):
            continue
        found[name] = d
    return found


def update(out_dir, jobs=8):
    """按 manifest 增量：no-op 仓跳过，变更仓重建合并图；标签与服务命名策略沿用 manifest 记录。"""
    roots, labels, prefixes = [], {}, {}
    for name, d in _read_manifests(out_dir).items():
        root = d["root"]
        roots.append(root)
        labels[root] = d.get("label", name)
        # 旧 manifest 无 service_prefix：沿用多仓发现模式的仓名前缀（既有行为）
        prefixes[root] = d["service_prefix"] if "service_prefix" in d else labels[root]
    if not roots:
        return None, None, []
    return build_many(roots, out_dir, jobs=jobs, merged_name=os.path.basename(os.path.abspath(out_dir)),
                      service_prefixes=prefixes, labels=labels)


def rebind(out_dir, label, new_root):
    """来源根移动后的显式重绑（AC-R01-02）：只改物理路径，逻辑身份（label → sid → 节点 ID）不变。"""
    mp = os.path.join(out_dir, label, "manifest.json")
    if not os.path.exists(mp):
        raise KeyError("未登记的来源标签：%s" % label)
    new_root = os.path.abspath(new_root)
    if not os.path.isdir(new_root):
        raise FileNotFoundError("新路径不存在或不是目录：%s" % new_root)
    with open(mp, encoding="utf-8") as f:
        d = json.load(f)
    old = d.get("root")
    d["root"] = new_root
    d.setdefault("label", label)
    tmp = mp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, mp)
    return {"label": label, "old_root": old, "root": new_root}
