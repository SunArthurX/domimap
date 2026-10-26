"""workspace — 整库导出/恢复（R07）：证据库 + blob + 不可变代 + 图 + 来源登记 + 知识库作为一个可校验包。

导出：对运行中的工作区取一致性快照（SQLite backup API），逐文件记 sha256 到 workspace-manifest.json，
暂存目录整体 rename 发布（目标已存在则拒绝）。查询日志 queries.db 默认不随包（roadmap §9：查询日志不外发），
`include_queries=True` 显式带上并在清单标注 contains_query_log。

恢复：目标必须不存在；逐成员校验路径不越界、非符号链接、sha256 一致、无缺件；在私有暂存目录内
恢复知识库（复用 KnowledgeStore.restore 的校验）、验证证据库 active 代可定位且 graph.json 字节等于该代；
全部通过后 rename 为目标。任一步失败不留半成品。
"""
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time

from .storage import sync_directory

SCHEMA = "domimap.workspace.v1"
MANIFEST = "workspace-manifest.json"
KNOWLEDGE_DIR = "knowledge"  # KnowledgeStore.backup 产出的 kbackup v2 目录


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _snapshot_sqlite(src, dst):
    """一致性快照：不持有源事务，backup API 自行处理并发写者。"""
    source = sqlite3.connect(src)
    target = sqlite3.connect(dst)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)


def _walk_files(base):
    for dp, dns, fns in os.walk(base):
        dns.sort()
        for fn in sorted(fns):
            p = os.path.join(dp, fn)
            yield os.path.relpath(p, base).replace(os.sep, "/"), p


def export_workspace(ws_dir, dest, include_queries=False):
    """导出 ws_dir（含 graph.json 的工作区目录）为 dest 目录；返回 workspace-manifest 内容。"""
    ws_dir = os.path.abspath(ws_dir)
    dest = os.path.abspath(dest)
    if os.path.lexists(dest):
        raise FileExistsError("export destination already exists: %s" % dest)
    store_db = os.path.join(ws_dir, "store.db")
    graph = os.path.join(ws_dir, "graph.json")
    for required in (store_db, graph):
        if not os.path.isfile(required):
            raise FileNotFoundError("workspace lacks %s (build first)" % os.path.basename(required))
    parent = os.path.dirname(dest)
    os.makedirs(parent, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".ws-export-", dir=parent)
    try:
        components = {"store": True, "graph": True, "coverage": False, "knowledge": False,
                      "queries": False, "sources": 0}
        _snapshot_sqlite(store_db, os.path.join(staging, "store.db"))
        _copy(graph, os.path.join(staging, "graph.json"))
        cov = os.path.join(ws_dir, "coverage.json")
        if os.path.isfile(cov):
            _copy(cov, os.path.join(staging, "coverage.json"))
            components["coverage"] = True
        for sub in ("blobs", "gens"):
            base = os.path.join(ws_dir, sub)
            if os.path.isdir(base):
                for rel, p in _walk_files(base):
                    if os.path.islink(p) or rel.endswith(".tmp"):
                        continue
                    _copy(p, os.path.join(staging, sub, rel))
        for name in sorted(os.listdir(ws_dir)):
            mp = os.path.join(ws_dir, name, "manifest.json")
            if os.path.isfile(mp):
                _copy(mp, os.path.join(staging, name, "manifest.json"))
                components["sources"] += 1
        kb = os.path.join(ws_dir, "knowledge.db")
        if os.path.isfile(kb):
            from .knowledge import KnowledgeStore
            k = KnowledgeStore(kb)
            try:
                k.backup(os.path.join(staging, KNOWLEDGE_DIR))
            finally:
                k.close()
            components["knowledge"] = True
        q = os.path.join(ws_dir, "queries.db")
        if include_queries and os.path.isfile(q):
            _snapshot_sqlite(q, os.path.join(staging, "queries.db"))
            components["queries"] = True
        files = {rel: _sha(p) for rel, p in _walk_files(staging)}
        active = None
        from .store import EvidenceStore
        st = EvidenceStore(os.path.join(staging, "store.db"))
        try:
            active = st.active_generation()
            counts = {"sources": st.db.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
                      "evidence": st.db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]}
        finally:
            st.close()
        manifest = {"schema": SCHEMA, "created": time.time(), "workspace": ws_dir,
                    "components": components, "counts": counts,
                    "active_generation_sha256": active["sha256"] if active else None,
                    "contains_query_log": components["queries"], "files": files}
        mp = os.path.join(staging, MANIFEST)
        with open(mp, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        sync_directory(staging)
        os.rename(staging, dest)
        sync_directory(parent)
        return manifest
    finally:
        if os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)


def _member(archive, rel):
    """清单成员必须是归档内的普通文件：拒绝绝对路径、..、符号链接与越界。"""
    if not isinstance(rel, str) or not rel or rel.startswith("/") or ".." in rel.split("/") or "\\" in rel:
        raise ValueError("illegal member path in manifest: %r" % (rel,))
    p = os.path.join(archive, *rel.split("/"))
    if os.path.islink(p) or any(os.path.islink(os.path.join(archive, *rel.split("/")[:i]))
                                for i in range(1, len(rel.split("/")))):
        raise ValueError("archive member is a symlink: %s" % rel)
    real = os.path.realpath(p)
    base = os.path.realpath(archive)
    if os.path.commonpath([real, base]) != base:
        raise ValueError("archive member escapes archive: %s" % rel)
    if not os.path.isfile(p):
        raise ValueError("archive member missing: %s" % rel)
    return p


def restore_workspace(archive, target):
    """把导出包恢复到不存在的 target 目录；返回摘要。任一校验失败不创建 target。"""
    archive = os.path.abspath(archive)
    target = os.path.abspath(target)
    if os.path.lexists(target):
        raise FileExistsError("restore requires a new target directory: %s" % target)
    mp = os.path.join(archive, MANIFEST)
    if os.path.islink(mp) or not os.path.isfile(mp):
        raise ValueError("archive member missing: %s" % MANIFEST)
    with open(mp, encoding="utf-8") as f:
        manifest = json.load(f)
    if manifest.get("schema") != SCHEMA or not isinstance(manifest.get("files"), dict):
        raise ValueError("unsupported workspace archive schema")
    files = manifest["files"]
    for required in ("store.db", "graph.json"):
        if required not in files:
            raise ValueError("archive member missing: %s" % required)
    parent = os.path.dirname(target)
    os.makedirs(parent, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".ws-restore-", dir=parent)
    try:
        for rel, expected in files.items():
            src = _member(archive, rel)
            if not isinstance(expected, str) or _sha(src) != expected:
                raise ValueError("sha256 mismatch for archive member: %s" % rel)
            if rel.startswith(KNOWLEDGE_DIR + "/"):
                continue  # 知识库经 KnowledgeStore.restore 校验后进入 knowledge.db
            _copy(src, os.path.join(staging, *rel.split("/")))
        summary = {"files": len(files), "knowledge": None}
        if manifest.get("components", {}).get("knowledge"):
            from .knowledge import KnowledgeStore
            kb = KnowledgeStore.restore(os.path.join(archive, KNOWLEDGE_DIR),
                                        os.path.join(staging, "knowledge.db"))
            try:
                summary["knowledge"] = {"notes": kb.count()}
            finally:
                kb.close()
        from .store import EvidenceStore
        st = EvidenceStore(os.path.join(staging, "store.db"))
        try:
            active = st.active_generation()
            if active is None:
                raise ValueError("restored evidence store has no readable active generation")
            if _sha(os.path.join(staging, "graph.json")) != active["sha256"]:
                raise ValueError("graph.json does not match the active generation")
            summary["nodes"] = active["nodes"]
            summary["evidence"] = st.db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
        finally:
            st.close()
        sync_directory(staging)
        os.rename(staging, target)
        sync_directory(parent)
        return summary
    finally:
        if os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)
