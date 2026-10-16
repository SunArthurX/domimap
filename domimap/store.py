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
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  sid TEXT PRIMARY KEY, repo TEXT, rel TEXT, sha256 TEXT, size INTEGER, first_seen REAL);
CREATE TABLE IF NOT EXISTS evidence (
  ev_id TEXT PRIMARY KEY, sid TEXT, locator TEXT, blob_sha TEXT, captured_at REAL);
CREATE TABLE IF NOT EXISTS generations (
  gen_id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT, sha256 TEXT,
  nodes INTEGER, edges INTEGER, status TEXT, created REAL);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS idx_evidence_sid ON evidence(sid);
"""

BLOB_LIMIT = 1 << 20  # 单来源固化片段上限（1MiB；超出截断并标注）


class EvidenceStore:
    def __init__(self, db_path):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.dir = os.path.dirname(os.path.abspath(db_path))
        self.blobs = os.path.join(self.dir, "blobs")
        self.gens = os.path.join(self.dir, "gens")
        os.makedirs(self.blobs, exist_ok=True)
        os.makedirs(self.gens, exist_ok=True)
        self.db = sqlite3.connect(db_path, timeout=30)
        self.db.executescript(SCHEMA)
        self.db.commit()
        self._fail_stage = None  # 测试注入口

    # ---------- 来源捕获（字节即哈希，内容寻址不可变） ----------
    def capture_source(self, repo, sid, abs_path, rel):
        with open(abs_path, "rb") as f:
            raw = f.read(BLOB_LIMIT + 1)
        truncated = len(raw) > BLOB_LIMIT
        raw = raw[:BLOB_LIMIT]
        sha = hashlib.sha256(raw).hexdigest()
        blob = os.path.join(self.blobs, sha)
        if not os.path.exists(blob):
            tmp = blob + ".tmp"
            with open(tmp, "wb") as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, blob)
        self.db.execute(
            "INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?)",
            (sid, repo, rel, sha, len(raw), time.time()))
        ev_id = "ev:" + sha[:20]
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            text = ""
        self.db.execute(
            "INSERT OR REPLACE INTO evidence VALUES (?,?,?,?,?)",
            (ev_id, sid, json.dumps({"rel": rel, "truncated": truncated}, ensure_ascii=False),
             sha, time.time()))
        self.db.commit()
        return {"sid": sid, "sha256": sha, "ev_id": ev_id}

    def list_sources(self):
        return [{"sid": r[0], "repo": r[1], "rel": r[2], "sha256": r[3]}
                for r in self.db.execute("SELECT sid,repo,rel,sha256 FROM sources")]

    def evidence_for_source(self, sid):
        row = self.db.execute(
            "SELECT ev_id,locator,blob_sha FROM evidence WHERE sid=? ORDER BY captured_at DESC LIMIT 1",
            (sid,)).fetchone()
        if not row:
            return None
        ev_id, locator, blob_sha = row
        path = os.path.join(self.blobs, blob_sha)
        if not os.path.exists(path):
            return {"ev_id": ev_id, "sid": sid, "available": False,
                    "reason": "blob 缺失（异常状态，非源删除）"}
        with open(path, "rb") as f:
            raw = f.read()
        return {"ev_id": ev_id, "sid": sid, "available": True,
                "locator": json.loads(locator), "sha256": blob_sha,
                "text": raw.decode("utf-8", errors="replace")}

    # ---------- generation 发布 ----------
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
            if self._fail_stage == "validate":
                raise RuntimeError("injected: validation failure")
            with open(final, encoding="utf-8") as f:
                check = json.load(f)
            if not check["nodes"]:
                raise RuntimeError("generation 无节点，拒绝发布")
            sha = hashlib.sha256(open(final, "rb").read()).hexdigest()
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

    def active_generation(self):
        """active 指针对应的完整代记录；文件不存在/损坏返回 None（调用方据此重建，不误报 no-op）。"""
        row = self.db.execute("SELECT value FROM meta WHERE key='active'").fetchone()
        if not row:
            return None
        rec = self.db.execute(
            "SELECT gen_id,path,sha256,nodes,edges,status FROM generations WHERE gen_id=?",
            (int(row[0]),)).fetchone()
        if not rec or rec[5] != "complete" or not os.path.exists(rec[1]):
            return None
        try:
            with open(rec[1], encoding="utf-8") as f:
                if not json.load(f).get("nodes"):
                    return None
        except Exception:
            return None
        return {"gen_id": rec[0], "path": rec[1], "sha256": rec[2],
                "nodes": rec[3], "edges": rec[4]}

    def seeds_digest(self):
        row = self.db.execute("SELECT value FROM meta WHERE key='seeds_sha256'").fetchone()
        return row[0] if row else None

    def set_seeds_digest(self, digest):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES ('seeds_sha256', ?)", (digest,))

    def close(self):
        self.db.close()
