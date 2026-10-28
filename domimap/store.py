"""store — 固化证据 + SQLite 元数据骨架 + 不可变 generation 发布（R02/R03）。

发布协议（顺序强制，文件系统与 SQLite 不构成单一原子事务）：
  1. 捕获来源字节 → 内容寻址 blob（blobs/{sha256}，只增不改）
  2. 图写 tmp → fsync → rename 为不可变 gens/gen-{N}.json
  3. 校验（JSON 可解析且 nodes>0）
  4. SQLite 事务：登记 generation + 切换 meta.active
任一阶段中断：读者只见上一完整代；blob 不可变 → 旧证据永久可读（源删除亦然）。
"""
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import threading
import time

from .storage import synchronized as _synchronized, sync_directory as _sync_directory, ensure_user_version, STORE_DB_VERSION

USER_VERSION = STORE_DB_VERSION

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  sid TEXT PRIMARY KEY, repo TEXT, rel TEXT, sha256 TEXT, size INTEGER, first_seen REAL);
CREATE TABLE IF NOT EXISTS evidence (
  ev_id TEXT PRIMARY KEY, sid TEXT, locator TEXT, blob_sha TEXT, captured_at REAL);
CREATE TABLE IF NOT EXISTS generations (
  gen_id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT, sha256 TEXT,
  nodes INTEGER, edges INTEGER, status TEXT, created REAL);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS content_first_seen (
  sha256 TEXT PRIMARY KEY, first_seen REAL);  -- 内容身份的最早出现时间：复制/重存不刷新（F4）
CREATE INDEX IF NOT EXISTS idx_evidence_sid ON evidence(sid);
"""

BLOB_LIMIT = 1 << 20  # 单来源固化片段上限（1MiB；超出截断并标注）


def _decode_evidence(raw):
    """证据片段读回：utf-8 严格，失败回退 gb18030（企业 Java 仓 GBK 注释），与扫描层解码一致。"""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gb18030", errors="replace")


class EvidenceStore:
    def __init__(self, db_path):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.dir = os.path.dirname(os.path.abspath(db_path))
        self.blobs = os.path.join(self.dir, "blobs")
        self.gens = os.path.join(self.dir, "gens")
        os.makedirs(self.blobs, exist_ok=True)
        os.makedirs(self.gens, exist_ok=True)
        # BEGIN only serializes separate connections; this lock also protects shared instances.
        self._lock = threading.RLock()
        self.db = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.db.commit()
        ensure_user_version(self.db, USER_VERSION, "store.db")
        self._fail_stage = None  # 测试注入口

    # ---------- 来源捕获（字节即哈希，内容寻址不可变） ----------
    @_synchronized
    def capture_source(self, repo, sid, abs_path, rel, raw=None):
        """固化一份来源字节。raw 由扫描器传入时不再读盘（哈希/解析/片段同源，D10）。"""
        if raw is None:
            with open(abs_path, "rb") as f:
                raw = f.read(BLOB_LIMIT + 1)
        truncated = len(raw) > BLOB_LIMIT
        raw = raw[:BLOB_LIMIT]
        sha = hashlib.sha256(raw).hexdigest()
        blob = os.path.join(self.blobs, sha)
        if os.path.islink(blob):
            raise ValueError("evidence blob is a symlink")
        if os.path.exists(blob):
            with open(blob, "rb") as f:
                if f.read(BLOB_LIMIT + 1) != raw:
                    raise ValueError("existing evidence blob failed integrity check")
        if not os.path.exists(blob):
            # Content may be shared across sources and concurrent processes. Never share tmp names.
            fd, tmp = tempfile.mkstemp(prefix=".capture-", dir=self.blobs)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(raw)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, blob)
                _sync_directory(self.blobs)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        locator = {"rel": rel, "truncated": truncated}
        identity = json.dumps([sid, sha, locator], ensure_ascii=False, sort_keys=True,
                              separators=(",", ":")).encode("utf-8")
        ev_id = "ev:" + hashlib.sha256(identity).hexdigest()
        now = time.time()
        with self.db:
            self.db.execute(
                "INSERT INTO content_first_seen VALUES (?,?) ON CONFLICT(sha256) DO UPDATE SET "
                "first_seen=min(first_seen, excluded.first_seen)", (sha, now))
            first_seen = self.db.execute(
                "SELECT first_seen FROM content_first_seen WHERE sha256=?", (sha,)).fetchone()[0]
            self.db.execute(
                "INSERT INTO sources VALUES (?,?,?,?,?,?) ON CONFLICT(sid) DO UPDATE SET "
                "rel=excluded.rel, sha256=excluded.sha256, size=excluded.size",
                (sid, repo, rel, sha, len(raw), first_seen))
            self.db.execute(
                "INSERT INTO evidence VALUES (?,?,?,?,?) ON CONFLICT(ev_id) DO NOTHING",
                (ev_id, sid, json.dumps(locator, ensure_ascii=False), sha, now))
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)",
                            ("source_evidence:" + sid, ev_id))
        return {"sid": sid, "sha256": sha, "ev_id": ev_id, "first_seen": first_seen}

    @_synchronized
    def list_sources(self):
        return [{"sid": r[0], "repo": r[1], "rel": r[2], "sha256": r[3]}
                for r in self.db.execute("SELECT sid,repo,rel,sha256 FROM sources")]

    @_synchronized
    def read_evidence(self, ev_id):
        """Read exactly this immutable record, including legacy content-only IDs.

        None means unknown ID. Missing/corrupt artifacts are explicit unavailable results;
        they never redirect to a newer capture or the live source file.
        """
        row = self.db.execute(
            "SELECT sid,locator,blob_sha FROM evidence WHERE ev_id=?", (ev_id,)).fetchone()
        if not row:
            return None
        sid, locator, blob_sha = row
        unavailable = {"ev_id": ev_id, "sid": sid, "available": False}
        if not isinstance(blob_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", blob_sha):
            return dict(unavailable, reason="invalid_blob_hash")
        path = os.path.join(self.blobs, blob_sha)
        if os.path.islink(path):
            return dict(unavailable, reason="blob_symlink")
        try:
            with open(path, "rb") as f:
                raw = f.read(BLOB_LIMIT + 1)
        except OSError:
            return dict(unavailable, reason="blob_unavailable")
        if len(raw) > BLOB_LIMIT or hashlib.sha256(raw).hexdigest() != blob_sha:
            return dict(unavailable, reason="blob_integrity_mismatch")
        try:
            locator = json.loads(locator)
            if not isinstance(locator, dict):
                raise ValueError("invalid locator")
        except (ValueError, TypeError):
            return dict(unavailable, reason="invalid_locator")
        return {"ev_id": ev_id, "sid": sid, "available": True,
                "locator": locator, "sha256": blob_sha,
                "text": _decode_evidence(raw)}

    @_synchronized
    def evidence_for_source(self, sid):
        """Explicit latest-source lookup, distinct from an immutable ID read."""
        row = self.db.execute(
            "SELECT e.ev_id FROM evidence e JOIN sources s ON s.sid=e.sid AND s.sha256=e.blob_sha "
            "LEFT JOIN meta m ON m.key='source_evidence:' || s.sid "
            "WHERE e.sid=? AND (m.value IS NULL OR e.ev_id=m.value) "
            "ORDER BY e.captured_at DESC,e.rowid DESC LIMIT 1", (sid,)).fetchone()
        return self.read_evidence(row[0]) if row else None

    @_synchronized
    def evidence_map(self):
        """Legacy graph file -> actual ID, only when that path identifies one source.

        Graphs without source IDs cannot safely disambiguate equal relative paths.
        Omit those links rather than letting the last captured repository win.
        """
        rows = self.db.execute(
            "SELECT s.rel,e.sid,e.ev_id FROM evidence e "
            "JOIN sources s ON s.sid=e.sid AND s.sha256=e.blob_sha "
            "LEFT JOIN meta m ON m.key='source_evidence:' || s.sid "
            "WHERE m.value IS NULL OR e.ev_id=m.value "
            "ORDER BY e.captured_at DESC,e.rowid DESC")
        by_rel = {}
        for rel, sid, ev_id in rows:
            by_rel.setdefault(rel, {}).setdefault(sid, ev_id)
        return {rel: next(iter(sources.values())) for rel, sources in by_rel.items()
                if len(sources) == 1}

    @_synchronized
    def evidence_by_sid(self):
        """sid → 当前指针指向的 ev_id（来源身份直达，不经相对路径猜测）。"""
        prefix = "source_evidence:"
        return {k[len(prefix):]: v for k, v in self.db.execute(
            "SELECT key, value FROM meta WHERE key LIKE ?", (prefix + "%",))}

    # ---------- 知识复核摘要（R06）：被引用的 ev_id 是不可变版本；"依据已变"= 同一来源出现更新版本 ----------
    @_synchronized
    def review_digests(self):
        """返回 {"cited": {ev_id: 自身 blob_sha}, "current": {ev_id|sid: 来源最新 blob_sha}, "latest": {ev_id: 最新 ev_id}}。"""
        prefix = "source_evidence:"
        latest_ev = {k[len(prefix):]: v for k, v in self.db.execute(
            "SELECT key, value FROM meta WHERE key LIKE ?", (prefix + "%",))}
        sha_of = {ev: sha for ev, sha in self.db.execute("SELECT ev_id, blob_sha FROM evidence")}
        cited, current, latest = {}, {}, {}
        for ev, sid, sha in self.db.execute("SELECT ev_id, sid, blob_sha FROM evidence"):
            cited[ev] = sha
            lv = latest_ev.get(sid)
            if lv and lv in sha_of:
                current[ev] = sha_of[lv]
                latest[ev] = lv
        for sid, lv in latest_ev.items():
            if lv in sha_of:
                current[sid] = sha_of[lv]
        return {"cited": cited, "current": current, "latest": latest}

    # ---------- 工作区元数据：可信上下文根与规则文件指纹（F3） ----------
    @_synchronized
    def meta_get(self, key):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    @_synchronized
    def meta_set(self, key, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))

    @_synchronized
    def meta_delete(self, key):
        with self.db:
            self.db.execute("DELETE FROM meta WHERE key=?", (key,))

    @_synchronized
    def register_trusted_root(self, label, path, level="repo"):
        """显式登记可信上下文根（AGENTS.md/SOUL.md 只从这里读）。

        level（RV04b）：repo=仓级规则（默认，可多个）；workspace=工作区基线（至多一个，
        第二个不同路径的 workspace 登记拒绝——分层必须无歧义）。优先序见 service.trusted_context。
        """
        if not label or "/" in label or label.startswith("."):
            raise ValueError("非法标签：%r" % (label,))
        if level not in ("repo", "workspace"):
            raise ValueError("level 须为 repo 或 workspace：%r" % (level,))
        real = os.path.realpath(path)
        if not os.path.isdir(real):
            raise FileNotFoundError("可信根不存在或不是目录：%s" % path)
        if level == "workspace":
            for r in self.trusted_roots():
                if r.get("level") == "workspace" and r["path"] != real:
                    raise ValueError(
                        "已有工作区基线 %s（%s）：分层必须唯一，先 trust remove %s 再登记新的"
                        % (r["label"], r["path"], r["label"]))
        rec = {"label": label, "path": real, "level": level, "registered_at": time.time()}
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)",
                            ("trusted_root:" + label, json.dumps(rec, ensure_ascii=False)))
        return rec

    @_synchronized
    def remove_trusted_root(self, label):
        with self.db:
            cur = self.db.execute("DELETE FROM meta WHERE key=?", ("trusted_root:" + label,))
            self.db.execute("DELETE FROM meta WHERE key LIKE ?", ("context_sha:" + label + "/%",))
        return cur.rowcount > 0

    @_synchronized
    def trusted_roots(self):
        rows = self.db.execute("SELECT value FROM meta WHERE key LIKE 'trusted_root:%' ORDER BY key").fetchall()
        return [json.loads(r[0]) for r in rows]

    # ---------- generation 发布 ----------
    @_synchronized
    def publish_graph(self, g, extra_meta=None):
        """按协议发布一代图；返回 gen 记录。失败（含注入）不切换 active。"""
        payload = {"nodes": list(g.nodes.values()), "edges": g.edges,
                   "schema": "domimap.lite.v1",
                   "meta": extra_meta or {}, "published_at": time.time()}
        try:
            return self._publish_locked(payload)
        except Exception:
            self.db.rollback()
            raise

    def _publish_locked(self, payload):
        import time as _t
        self.db.execute("BEGIN EXCLUSIVE")  # 并发写者串行化：gen_id 分配与登记同一事务
        try:
            gen_id = 1 + (self.db.execute("SELECT COALESCE(MAX(gen_id),0) FROM generations").fetchone()[0])
            final = os.path.join(self.gens, "gen-%04d.json" % gen_id)
            tmp = final + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            if self._fail_stage == "before-rename":
                raise RuntimeError("injected: before rename")
            os.replace(tmp, final)
            _sync_directory(self.gens)
            if self._fail_stage == "validate":
                raise RuntimeError("injected: validation failure")
            with open(final, encoding="utf-8") as f:
                check = json.load(f)
            if not check["nodes"]:
                raise RuntimeError("generation 无节点，拒绝发布")
            with open(final, "rb") as f:
                sha = hashlib.sha256(f.read()).hexdigest()
            if self._fail_stage == "before-tx":
                raise RuntimeError("injected: before transaction")
            self.db.execute("INSERT INTO generations VALUES (?,?,?,?,?,?,?)",
                            (gen_id, final, sha, len(check["nodes"]), len(check["edges"]),
                             "complete", _t.time()))
            self.db.execute("INSERT OR REPLACE INTO meta VALUES ('active', ?)", (str(gen_id),))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {"gen_id": gen_id, "path": final, "sha256": sha}

    @_synchronized
    def active_generation(self):
        """active 指针对应的完整代记录；文件不存在/损坏返回 None（调用方据此重建，不误报 no-op）。"""
        row = self.db.execute("SELECT value FROM meta WHERE key='active'").fetchone()
        if not row:
            return None
        rec = self.db.execute(
            "SELECT gen_id,path,sha256,nodes,edges,status FROM generations WHERE gen_id=?",
            (int(row[0]),)).fetchone()
        if not rec or rec[5] != "complete":
            return None
        path = self._gen_path(rec[1])
        if path is None:
            return None
        try:
            with open(path, "rb") as f:
                raw = f.read()
            if hashlib.sha256(raw).hexdigest() != rec[2] or not json.loads(raw).get("nodes"):
                return None
        except Exception:
            return None
        return {"gen_id": rec[0], "path": path, "sha256": rec[2],
                "nodes": rec[3], "edges": rec[4]}

    def _gen_path(self, recorded):
        """代文件按发布时绝对路径定位；工作区被移动/恢复到别处时退回到本库旁的 gens/ 同名文件。"""
        if os.path.exists(recorded):
            return recorded
        local = os.path.join(self.gens, os.path.basename(recorded))
        return local if os.path.exists(local) else None

    @_synchronized
    def generation_sources_by_sha(self, sha256):
        """按图字节 sha 定位其所属不可变代，返回该代 meta.sources（无该代或无 sources 键 → None）。"""
        row = self.db.execute(
            "SELECT path FROM generations WHERE sha256=? AND status='complete'", (sha256,)).fetchone()
        if not row:
            return None
        path = self._gen_path(row[0])
        if not path:
            return None
        try:
            with open(path, encoding="utf-8") as f:
                gen = json.load(f)
        except (OSError, ValueError):
            return None
        sources = (gen.get("meta") or {}).get("sources")
        return sources if isinstance(sources, dict) and sources else None

    @_synchronized
    def seeds_digest(self):
        row = self.db.execute("SELECT value FROM meta WHERE key='seeds_sha256'").fetchone()
        return row[0] if row else None

    @_synchronized
    def set_seeds_digest(self, digest):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES ('seeds_sha256', ?)", (digest,))

    @_synchronized
    def prune_generations(self, keep=2):
        """只留最新的 keep 代（以及当前 active）。更旧的代文件删除。证据 blob 不动。"""
        keep = max(1, int(keep))
        active_row = self.db.execute("SELECT value FROM meta WHERE key='active'").fetchone()
        active = int(active_row[0]) if active_row else None
        rows = self.db.execute(
            "SELECT gen_id, path FROM generations ORDER BY gen_id DESC").fetchall()
        keep_ids = {row[0] for row in rows[:keep]}
        if active is not None:
            keep_ids.add(active)
        removed = []
        for gen_id, path in rows:
            if gen_id in keep_ids:
                continue
            local = self._gen_path(path)
            if local and os.path.isfile(local) and not os.path.islink(local):
                os.remove(local)
            self.db.execute("DELETE FROM generations WHERE gen_id=?", (gen_id,))
            removed.append(gen_id)
        self.db.commit()
        return removed

    @_synchronized
    def prune_unreferenced_blobs(self):
        """删掉证据表和来源表都不再引用的 blob 文件。被引用的历史片段保留。"""
        referenced = {row[0] for row in self.db.execute("SELECT blob_sha FROM evidence")}
        referenced.update(row[0] for row in self.db.execute("SELECT sha256 FROM sources") if row[0])
        removed = []
        if not os.path.isdir(self.blobs):
            return removed
        for name in os.listdir(self.blobs):
            if not re.fullmatch(r"[0-9a-f]{64}", name) or name in referenced:
                continue
            path = os.path.join(self.blobs, name)
            if os.path.isfile(path) and not os.path.islink(path):
                os.remove(path)
                removed.append(name)
        return removed

    @_synchronized
    def close(self):
        self.db.close()


class EvidenceResolver:
    """Resolve a graph node to its evidence ID, bound to the generation the served graph belongs to.

    Resolution order (RV01):
    1. graph sha → the immutable generation those exact bytes were published as → that
       generation's meta.sources map (sid → ev_id). A graph file keeps resolving to the evidence
       versions it was built from, even if newer captures exist or the store's active pointer
       already moved on (interrupted publication windows stay consistent).
    2. Legacy fallback: the store's latest per-source pointers (graphs published before
       generations carried a sources map).
    3. Unique-relative-path map for graphs built before nodes carried sids (D11).
    """

    def __init__(self, store=None, graph_sha=None):
        self.by_sid = {}
        if store is not None:
            if graph_sha:
                sources = store.generation_sources_by_sha(graph_sha)
                if sources is not None:
                    self.by_sid = {sid: rec["ev_id"] for sid, rec in sources.items()}
            if not self.by_sid:
                self.by_sid = store.evidence_by_sid()
        self.by_rel = store.evidence_map() if store else {}

    @classmethod
    def beside(cls, graph_path):
        """Bind to the graph file being served: resolve via its own generation when possible."""
        import hashlib as _h
        db = os.path.join(os.path.dirname(os.path.abspath(graph_path)), "store.db")
        if not os.path.exists(db):
            return cls(None)
        sha = None
        try:
            with open(graph_path, "rb") as f:
                sha = _h.sha256(f.read()).hexdigest()
        except OSError:
            sha = None
        store = EvidenceStore(db)
        try:
            return cls(store, graph_sha=sha)
        finally:
            store.close()

    def for_node(self, node):
        sid = (node.get("meta") or {}).get("sid")
        if sid and sid in self.by_sid:
            return self.by_sid[sid]
        return self.by_rel.get(node.get("file"))

    def get(self, rel):
        """Legacy rel lookup (kept for callers that only have a path)."""
        return self.by_rel.get(rel)
