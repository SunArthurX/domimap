"""batch — 多仓发现、并行批量构建、跨仓合并图、仓级增量更新。

增量策略（仓级粒度）：manifest 记录每个文件的内容 sha256（D12：mtime/size 不是内容版本，
cp -p / touch -r 后的同尺寸改写也能识别）；update 重算哈希比对——不变即 no-op，变化则整仓重建。
派生产物（graph.json/coverage.json/manifest.json）一律 tmp+fsync+rename 原子落盘；
兼容副本 graph.json 的内容哈希须等于 active 代，否则视为不健康并重发布。
"""
import hashlib
import json
import os
import tempfile
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

from . import lite_scan
from .graph import Graph

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

def _file_sha256(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def _git_index_and_dirty(root):
    """干净的已跟踪文件用 index 里的 blob id，不读工作区。失败返回 None。"""
    import subprocess
    try:
        listed = subprocess.run(
            ["git", "-C", root, "ls-files", "-s", "-z"],
            capture_output=True, check=True)
        status = subprocess.run(
            ["git", "-C", root, "status", "--porcelain", "-z", "-uall"],
            capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    indexed = {}
    for rec in listed.stdout.split(b"\0"):
        if not rec:
            continue
        meta, _, path = rec.partition(b"\t")
        parts = meta.split()
        if len(parts) < 2 or not path:
            continue
        indexed[path.decode("utf-8", "surrogateescape")] = parts[1].decode("ascii")
    dirty = set()
    items = status.stdout.split(b"\0")
    i = 0
    while i < len(items):
        rec = items[i]
        i += 1
        if len(rec) < 4:
            continue
        path = rec[3:].decode("utf-8", "surrogateescape")
        dirty.add(path)
        if rec[:2] in (b"R ", b"RM", b"C "):  # 下一条是新路径
            if i < len(items) and items[i]:
                dirty.add(items[i].decode("utf-8", "surrogateescape"))
                i += 1
    return indexed, dirty


def repo_signature(root):
    """文件 → 内容签名。Git 仓里未改动的已跟踪文件用 blob id；其余读字节做 sha256。"""
    git = _git_index_and_dirty(root) if os.path.isdir(os.path.join(root, ".git")) or os.path.isfile(os.path.join(root, ".git")) else None
    indexed, dirty = git if git else ({}, set())
    sig = {}
    for path, rel in lite_scan._walk(root):
        rel_key = rel.replace("\\", "/")
        if git and rel_key in indexed and rel_key not in dirty:
            sig[rel] = "git:" + indexed[rel_key]
            continue
        digest = _file_sha256(path)
        if digest:
            sig[rel] = digest
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

def _save_record_cache(path, records, signature):
    """解析结果缓存：与 manifest 的文件签名一起存，签名不一致则作废。"""
    keep = ("classes", "methods", "routes", "rpc", "topics", "sqlstmts", "tables", "pages",
            "docs", "entities", "modules", "jobs", "calls", "services", "coverage")
    payload = {k: records.get(k) for k in keep}
    payload["_signature"] = signature
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _atomic_write(path, json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _load_record_cache(path, signature):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("_signature") != signature:
        return None
    data.pop("_signature", None)
    return data


def normalized(g):
    """规范化等价视图（增量=全量收敛比较用）：(节点ID集, 规范化边五元组集)。"""
    return (frozenset(g.nodes),
            frozenset((e["src"], e["dst"], e["kind"], e["conf"], e["prov"]) for e in g.edges))


def _seeds_digest(out_dir):
    """包内种子，加上工作区 domimap.seeds.json（没有则与旧摘要相同，不强迫既有库重建）。"""
    pkg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seeds.json")
    h = hashlib.sha256()
    with open(pkg, "rb") as f:
        h.update(f.read())
    extra = os.path.join(out_dir, "domimap.seeds.json") if out_dir else ""
    if extra and os.path.exists(extra):
        with open(extra, "rb") as f:
            h.update(b"\n")
            h.update(f.read())
    return h.hexdigest()

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


RECORD_LISTS = ("classes", "methods", "routes", "rpc", "topics", "sqlstmts", "tables", "pages", "docs", "entities", "modules", "jobs")


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
    """tmp → fsync → rename → 目录 fsync：读者只会看到完整的旧文件或完整的新文件（D12）。

    临时名每次唯一。同一 out 目录上的两个构建不能共用 path.tmp，否则一方 replace 后另一方报文件不存在。
    """
    from .storage import sync_directory
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", dir=directory)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
    sync_directory(directory)


def _capture_into(store, label, signature, first_seen=None, sources=None):
    """扫描回调：同一份字节既固化为证据（D10），也产出 manifest 的内容签名（D12），不再二次读盘。

    first_seen[rel] 记录该内容的首次收录时间（store 按内容 sha 取 min）：复制/touch 不刷新（F4）。
    sources[sid] 记录本次构建实际使用的来源版本（rel/sha/ev_id）——随图进入同一不可变代（RV01）：
    提前捕获的新版本不得给旧图背书，解析按图所属代的 sources 进行。
    """
    def capture(path, rel, raw):
        signature[rel] = hashlib.sha256(raw).hexdigest()
        rec = store.capture_source(label, label + "|" + rel, path, rel, raw=raw)
        if first_seen is not None:
            first_seen[rel] = rec["first_seen"]
        if sources is not None:
            sources[rec["sid"]] = {"repo": label, "rel": rel,
                                   "sha256": rec["sha256"], "ev_id": rec["ev_id"]}
    return capture


def _publish_compat_copy(gen_path, json_path):
    """graph.json 与代文件同一份字节。优先硬链接；不支持时再整份复制。

    先链到临时名再 replace，中断时旧的 graph.json 还在。
    """
    directory = os.path.dirname(os.path.abspath(json_path)) or "."
    os.makedirs(directory, exist_ok=True)
    stale = json_path + ".link"
    if os.path.lexists(stale):
        try:
            os.remove(stale)
        except OSError:
            pass
    fd, tmp = tempfile.mkstemp(prefix=".graph.json.", dir=directory)
    os.close(fd)
    os.unlink(tmp)
    try:
        os.link(gen_path, tmp)
    except OSError:
        if os.path.lexists(tmp):
            os.remove(tmp)
        with open(gen_path, "rb") as f:
            _atomic_write(json_path, f.read())
        return
    os.replace(tmp, json_path)


def publish_generation(store, g, out_dir, sources=None):
    """发布协议：不可变代（含 sources 版本映射）→ seeds 摘要 → graph.json 与代文件同一 inode（或复制）。"""
    rec = store.publish_graph(g, extra_meta={"sources": sources or {}})
    store.set_seeds_digest(_seeds_digest(out_dir))
    from .graphdb import write_graph_db
    json_path = os.path.join(out_dir, "graph.json")
    _publish_compat_copy(rec["path"], json_path)
    st = os.stat(json_path)
    write_graph_db(g, os.path.join(out_dir, "graph.db"),
                   source_size=st.st_size, source_mtime_ns=st.st_mtime_ns)
    return rec

def refresh_reviews(out_dir, store):
    """R06：发布新代后，把"依据已变"的知识陈述送入待复核队列（只增队列/基线，不改人工正文）。

    基线 = 陈述引用的那个 ev_id 自身版本（不随扫描推进）；当前 = 同一来源最新版本；不同即入队。
    knowledge.db 不存在则无事。返回当前队列。
    """
    kb_path = os.path.join(out_dir, "knowledge.db")
    if not os.path.exists(kb_path):
        return []
    from .knowledge import KnowledgeStore
    d = store.review_digests()
    kb = KnowledgeStore(kb_path)
    try:
        kb.record_baseline(d["cited"], overwrite=False)
        return kb.scan_dependencies(d["current"], latest_keys=d["latest"])
    finally:
        kb.close()


def _store_healthy(out_dir):
    from .store import EvidenceStore
    db = os.path.join(out_dir, "store.db")
    if not os.path.exists(db):
        return False
    store = EvidenceStore(db)
    try:
        active = store.active_generation()
        if active is None or store.seeds_digest() != _seeds_digest(out_dir):
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

def _scan_root_process(job):
    """子进程扫一个仓：源文件只读一次，截断后的字节写入 spool，不碰主库。"""
    root, label, prefix, rules, spool = job
    os.makedirs(spool, exist_ok=True)
    from .store import BLOB_LIMIT
    signature, blob_of = {}, {}

    def capture(path, rel, raw):
        signature[rel] = hashlib.sha256(raw).hexdigest()
        chunk = raw[:BLOB_LIMIT]
        sha = hashlib.sha256(chunk).hexdigest()
        blob_of[rel] = sha
        dest = os.path.join(spool, sha)
        if not os.path.exists(dest):
            tmp = dest + ".tmp"
            with open(tmp, "wb") as f:
                f.write(chunk)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, dest)

    from . import lite_scan
    records = lite_scan.scan_repo(root, repo_label=prefix, rules=rules, capture=capture)
    return {"root": root, "label": label, "records": records, "signature": signature, "blob_of": blob_of}


def _import_spool(store, label, spool, blob_of, first_seen, sources):
    """主进程把 spool 里的字节登记进证据库。不再读源文件。"""
    for rel, sha in blob_of.items():
        with open(os.path.join(spool, sha), "rb") as f:
            raw = f.read()
        rec = store.capture_source(label, label + "|" + rel, "", rel, raw=raw)
        first_seen[rel] = rec["first_seen"]
        sources[rec["sid"]] = {"repo": label, "rel": rel, "sha256": rec["sha256"], "ev_id": rec["ev_id"]}


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
    from .graph import load_workspace_seeds
    seeds = load_workspace_seeds(out_dir)
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
        generation_sources = {}
        rules = None
        rules_path = os.path.join(out_dir, "rules.json")
        if os.path.exists(rules_path):
            try:
                with open(rules_path, encoding="utf-8") as f:
                    rules = json.load(f)
            except (OSError, json.JSONDecodeError):
                rules = None

        def scan(root):
            label = label_of(root)
            sig = signatures.setdefault(root, {})
            seen = {}
            R = lite_scan.scan_repo(root, repo_label=prefix_of(root), rules=rules,
                                    capture=_capture_into(store, label, sig, seen, generation_sources))
            return _stamp_sid(R, label, seen)
        Rs = {}
        use_procs = jobs > 1 and len(dirty) > 1
        if use_procs:
            import tempfile
            spools = {}
            jobs_arg = []
            for root in dirty:
                spool = tempfile.mkdtemp(prefix="dm-spool-")
                spools[root] = spool
                jobs_arg.append((root, label_of(root), prefix_of(root), rules, spool))
            try:
                with ProcessPoolExecutor(max_workers=min(jobs, len(dirty))) as ex:
                    for item in ex.map(_scan_root_process, jobs_arg):
                        root = item["root"]
                        seen = {}
                        _import_spool(store, item["label"], spools[root], item["blob_of"],
                                      seen, generation_sources)
                        signatures[root] = item["signature"]
                        Rs[root] = _stamp_sid(item["records"], item["label"], seen)
            finally:
                for spool in spools.values():
                    for name in os.listdir(spool):
                        try:
                            os.remove(os.path.join(spool, name))
                        except OSError:
                            pass
                    try:
                        os.rmdir(spool)
                    except OSError:
                        pass
        else:
            with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
                for root, R in zip(dirty, ex.map(scan, dirty)):
                    Rs[root] = R
        merged = {"services": {}, "classes": [], "methods": [], "routes": [], "rpc": [],
                  "topics": [], "sqlstmts": [], "tables": [], "pages": [], "docs": [], "entities": [],
                  "modules": [], "jobs": [], "calls": [],
                  "coverage": {"files_scanned": 0, "skipped": []}}
        manifests_pending = []
        # 未变更仓复用 records.json（签名与 manifest 一致才用）；没有缓存才重扫
        for root in roots:
            label = label_of(root)
            R = Rs.get(root)
            sig = signatures.get(root)
            if R is None:
                mpath = os.path.join(out_dir, label, "manifest.json")
                try:
                    with open(mpath, encoding="utf-8") as f:
                        sig = json.load(f).get("files") or {}
                except (OSError, json.JSONDecodeError):
                    sig = None
                R = _load_record_cache(os.path.join(out_dir, label, "records.json"), sig) if sig else None
            if R is None:
                R = scan(root)
                sig = signatures.get(root) or {}
            if sig:
                _save_record_cache(os.path.join(out_dir, label, "records.json"), R, sig)
            for k in ("classes", "methods", "routes", "rpc", "topics", "sqlstmts", "tables", "pages", "docs", "entities", "modules", "jobs", "calls"):
                merged[k].extend(R.get(k) or [])
            merged["services"].update(R["services"])
            merged["coverage"]["files_scanned"] += R["coverage"]["files_scanned"]
            merged["coverage"]["skipped"].extend(R["coverage"]["skipped"])
            mdir = os.path.join(out_dir, label)
            os.makedirs(mdir, exist_ok=True)
            from . import __version__ as _v
            manifests_pending.append(
                (os.path.join(mdir, "manifest.json"),
                 json.dumps({"root": os.path.abspath(root), "label": label, "tool_version": _v,
                             "service_prefix": prefix_of(root),
                             "files": repo_signature(root) if (
                                 os.path.isdir(os.path.join(root, ".git"))
                                 or os.path.isfile(os.path.join(root, ".git")))
                             else (signatures.get(root) or repo_signature(root))},
                            ensure_ascii=False).encode("utf-8")))
        g = Graph()
        g.build_from_records(merged, seeds)
        publish_generation(store, g, out_dir, generation_sources)
        # RV01：manifest 记录的是"已发布完成"的来源状态——只在发布成功后落盘；
        # 发布前中断时 manifest 未动，下一次 update 依旧 manifest 判脏并重建，不误报 no-op。
        for mpath, mdata in manifests_pending:
            _atomic_write(mpath, mdata)
        refresh_reviews(out_dir, store)
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
