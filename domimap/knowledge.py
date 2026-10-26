"""knowledge — 人工知识事务层（M3.1，R05）。

SQLite 短事务（BEGIN IMMEDIATE）实现：
  submit(body, claims, idempotency_key)   新建/幂等重放/同键异内容冲突
  amend(note_id, body, expected_revision) 乐观锁防覆盖，历史修订全留
  withdraw(note_id)                        撤回（状态 withdrawn，历史保留）
  accept_claim(note_id, idx)               接受推断（accepted ≠ extracted）

机器图重建不得触碰本层（R05 双通道）。_fail_stage 为测试注入口（pre-commit 中断）。
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid

from .storage import synchronized, read_snapshot, sync_directory

SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge (
  note_id TEXT PRIMARY KEY, body TEXT, revision INTEGER, status TEXT,
  created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS claims (
  note_id TEXT, idx INTEGER, type TEXT, statement TEXT, evidence TEXT,
  scope TEXT, state TEXT, PRIMARY KEY (note_id, idx));
CREATE TABLE IF NOT EXISTS revisions (
  note_id TEXT, revision INTEGER, snapshot TEXT, created REAL,
  PRIMARY KEY (note_id, revision));
CREATE TABLE IF NOT EXISTS idempotency (
  key TEXT PRIMARY KEY, note_id TEXT, content_sha TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS baselines (
  evkey TEXT PRIMARY KEY, sha TEXT, recorded REAL);
CREATE TABLE IF NOT EXISTS review_pending (
  note_id TEXT, claim_idx INTEGER, evkey TEXT, old_sha TEXT, new_sha TEXT, since REAL,
  PRIMARY KEY (note_id, claim_idx, new_sha));
CREATE TABLE IF NOT EXISTS claim_bindings (
  note_id TEXT, claim_idx INTEGER, sha TEXT, confirmed_at REAL,
  PRIMARY KEY (note_id, claim_idx));
CREATE TABLE IF NOT EXISTS usage (
  note_id TEXT PRIMARY KEY, hits INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS tombstones (
  note_id TEXT PRIMARY KEY, reason TEXT, forgotten_at REAL);  -- 受管遗忘：可审计，过期清理
"""

CLAIM_TYPES = {"requirement", "implementation", "observation", "decision", "inference"}
BACKUP_TABLES = ("knowledge", "claims", "revisions", "idempotency", "baselines",
                 "review_pending", "claim_bindings", "usage", "tombstones")


def _table_counts(db):
    return {table: db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            for table in BACKUP_TABLES}


def _file_sha(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_backup_database(db):
    """Compare structure with our own schema without executing SQL from the archive."""
    if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
        raise ValueError("backup database integrity check failed")
    if db.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view') LIMIT 1").fetchone():
        raise ValueError("backup contains unsupported schema objects")
    reference = sqlite3.connect(":memory:")
    try:
        reference.executescript(SCHEMA)
        for table in BACKUP_TABLES:
            statement = "PRAGMA table_info(" + table + ")"
            if db.execute(statement).fetchall() != reference.execute(statement).fetchall():
                raise ValueError("backup table schema mismatch: " + table)
    finally:
        reference.close()
    return _table_counts(db)

# LLM 增强笔记（product-llm-enrich）的 body 前缀：检索层据此标注 conf=LLM/prov=knowledge:llm。
# 产物一律 inference 型草稿（state=proposed），人工 accept/confirm 前不作为确认知识。
LLM_NOTE_PREFIX = "【LLM 摘要｜"


def attach_if_present(searcher, graph_path):
    """图旁 knowledge.db 存在时把 active 笔记挂进检索（CLI query / MCP / UI 共用入口）。

    不存在则静默跳过（纯离线工作区不受影响）。返回是否挂接。
    """
    path = os.path.join(os.path.dirname(os.path.abspath(graph_path)), "knowledge.db")
    if not os.path.exists(path):
        return False
    kb = KnowledgeStore(path)
    try:
        searcher.attach_knowledge(kb)
    finally:
        kb.close()
    return True


class ConflictError(ValueError):
    """幂等键内容不一致 / expected_revision 过期。"""


class KnowledgeStore:
    def __init__(self, db_path):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        # Transactions belong to a connection; BEGIN does not isolate its calling threads.
        self._lock = threading.RLock()
        self.db = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.commit()
        self._fail_stage = None

    def _content_sha(self, body, claims):
        return hashlib.sha256(json.dumps(
            {"body": body, "claims": claims}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def _snapshot(self, note_id, body, claims, revision):
        self.db.execute("INSERT OR REPLACE INTO revisions VALUES (?,?,?,?)",
                        (note_id, revision, json.dumps(
                            {"body": body, "claims": claims}, ensure_ascii=False), time.time()))

    # ---- API ----
    @synchronized
    def submit(self, body, claims=None, idempotency_key=None):
        claims = self._check_claims(claims or [])
        key = idempotency_key or ("auto-" + uuid.uuid4().hex)
        sha = self._content_sha(body, claims)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute(
                "SELECT note_id, content_sha, result FROM idempotency WHERE key=?", (key,)).fetchone()
            if row:
                if row[1] != sha:
                    raise ConflictError("幂等键内容不一致: %s" % key)
                return json.loads(row[2])  # 原结果重放
            note_id = "note:" + uuid.uuid4().hex[:12]
            now = time.time()
            self.db.execute("INSERT INTO knowledge VALUES (?,?,?,?,?,?)",
                            (note_id, body, 1, "active", now, now))
            for i, c in enumerate(claims):
                self.db.execute("INSERT INTO claims VALUES (?,?,?,?,?,?,?)",
                                (note_id, i, c["type"], c.get("statement", ""),
                                 json.dumps(c.get("evidence", []), ensure_ascii=False),
                                 c.get("scope", ""), "proposed"))
            self._snapshot(note_id, body, claims, 1)
            result = {"note_id": note_id, "revision": 1, "status": "active"}
            self.db.execute("INSERT INTO idempotency VALUES (?,?,?,?)",
                            (key, note_id, sha, json.dumps(result, ensure_ascii=False)))
            if self._fail_stage == "pre-commit":  # 测试注入：提交前中断
                raise RuntimeError("injected: pre-commit")
            self.db.commit()
            return result

    @synchronized
    def amend(self, note_id, body, expected_revision, claims=None):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            cur = self.db.execute(
                "SELECT revision FROM knowledge WHERE note_id=? AND status='active'",
                (note_id,)).fetchone()
            if not cur:
                raise ConflictError("知识不存在或已撤回: %s" % note_id)
            if cur[0] != expected_revision:
                raise ConflictError(
                    "expected_revision 过期：当前 %d ≠ 期望 %d（防覆盖）" % (cur[0], expected_revision))
            new_rev = cur[0] + 1
            if claims is not None:
                claims = self._check_claims(claims)
                self.db.execute("DELETE FROM claims WHERE note_id=?", (note_id,))
                for i, c in enumerate(claims):
                    self.db.execute("INSERT INTO claims VALUES (?,?,?,?,?,?,?)",
                                    (note_id, i, c["type"], c.get("statement", ""),
                                     json.dumps(c.get("evidence", []), ensure_ascii=False),
                                     c.get("scope", ""), "proposed"))
                snap_claims = claims
            else:
                snap_claims = [dict(c) for c in self._claims_of(note_id)]
            self.db.execute("UPDATE knowledge SET body=?, revision=?, updated=? WHERE note_id=?",
                            (body, new_rev, time.time(), note_id))
            self._snapshot(note_id, body, snap_claims, new_rev)
            self.db.commit()
            return {"note_id": note_id, "revision": new_rev, "status": "active"}

    @synchronized
    def withdraw(self, note_id):
        with self.db:
            self.db.execute("UPDATE knowledge SET status='withdrawn', updated=? WHERE note_id=?",
                            (time.time(), note_id))
            self.db.commit()

    @synchronized
    def accept_claim(self, note_id, idx):
        with self.db:
            self.db.execute("UPDATE claims SET state='accepted' WHERE note_id=? AND idx=?",
                            (note_id, idx))
            self.db.commit()

    @read_snapshot
    def get(self, note_id):
        row = self.db.execute(
            "SELECT note_id, body, revision, status FROM knowledge WHERE note_id=?",
            (note_id,)).fetchone()
        if not row:
            return None
        return {"note_id": row[0], "body": row[1], "revision": row[2], "status": row[3],
                "claims": self._claims_of(note_id)}

    @synchronized
    def history(self, note_id):
        return [{"revision": r[0], "snapshot": json.loads(r[1]), "created": r[2]}
                for r in self.db.execute(
                    "SELECT revision, snapshot, created FROM revisions WHERE note_id=? "
                    "ORDER BY revision", (note_id,))]

    @read_snapshot
    def list_active(self):
        return [{"note_id": r[0], "body": r[1], "updated": r[2], "claims": self._claims_of(r[0])}
                for r in self.db.execute(
                    "SELECT note_id, body, updated FROM knowledge WHERE status='active' "
                    "ORDER BY updated DESC")]

    # ---------- R06：依赖失效复核 ----------
    @synchronized
    def record_baseline(self, current):
        """登记证据键基线摘要（扫描方提供，如 EvidenceStore 的 sha 映射）。"""
        with self.db:
            for key, sha in current.items():
                self.db.execute("INSERT OR REPLACE INTO baselines VALUES (?,?,?)",
                                (key, sha, time.time()))

    @synchronized
    def scan_dependencies(self, current):
        """当前摘要 vs 基线：仅受影响 claim 入待复核队列（幂等，主键去重）。

        点击/使用频率不参与（真实性只由确认绑定或修改/撤回改变）。
        """
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            old = {r[0]: r[1] for r in self.db.execute("SELECT evkey, sha FROM baselines")}
            queue = []
            for note in self.db.execute(
                    "SELECT note_id FROM knowledge WHERE status='active'"):
                note_id = note[0]
                for idx, ev_json in self.db.execute(
                        "SELECT idx, evidence FROM claims WHERE note_id=?", (note_id,)):
                    for evkey in json.loads(ev_json or "[]"):
                        if evkey in current and evkey in old and current[evkey] != old[evkey]:
                            bound = self.db.execute(
                                "SELECT sha FROM claim_bindings WHERE note_id=? AND claim_idx=?",
                                (note_id, idx)).fetchone()
                            if bound and bound[0] == current[evkey]:
                                continue  # 已确认绑定当前版本
                            self.db.execute(
                                "INSERT OR IGNORE INTO review_pending VALUES (?,?,?,?,?,?)",
                                (note_id, idx, evkey, old[evkey], current[evkey], time.time()))
            for r in self.db.execute(
                    "SELECT note_id, claim_idx, evkey, old_sha, new_sha FROM review_pending"):
                queue.append({"note_id": r[0], "claim_idx": r[1], "evidence": r[2],
                              "old_sha": r[3], "new_sha": r[4],
                              "actions": ["confirm(绑定新证据)", "amend(修改)", "withdraw(撤回)"]})
            self.db.commit()
            return queue

    @synchronized
    def confirm_review(self, note_id, claim_idx, new_evidence, new_sha):
        """确认 = 显式绑定新证据摘要（不是点击即真）。"""
        with self.db:
            self.db.execute("UPDATE claims SET evidence=?, state='confirmed' "
                            "WHERE note_id=? AND idx=?",
                            (json.dumps(new_evidence, ensure_ascii=False), note_id, claim_idx))
            self.db.execute("INSERT OR REPLACE INTO claim_bindings VALUES (?,?,?,?)",
                            (note_id, claim_idx, new_sha, time.time()))
            self.db.execute("DELETE FROM review_pending WHERE note_id=? AND claim_idx=?",
                            (note_id, claim_idx))
            self.db.commit()

    @synchronized
    def touch_note(self, note_id):
        """使用/点击计数——显式不影响复核状态与真实性（R06-02 负例语义）。"""
        with self.db:
            self.db.execute("INSERT INTO usage VALUES (?, 1) ON CONFLICT(note_id) "
                            "DO UPDATE SET hits = hits + 1", (note_id,))
            self.db.commit()

    # ---------- R07-03：受管遗忘与硬删 ----------
    @synchronized
    def forget(self, note_id, reason=""):
        """主动遗忘：主表/检索/导出移除，留墓碑（审计+保留期）。
        历史备份不受影响（备份时点语义，效果可解释）。"""
        with self.db:
            if self.get(note_id):
                self.db.execute("INSERT OR REPLACE INTO tombstones VALUES (?,?,?)",
                                (note_id, reason, time.time()))
                self.db.execute("DELETE FROM knowledge WHERE note_id=?", (note_id,))
                self.db.execute("DELETE FROM claims WHERE note_id=?", (note_id,))
                self.db.commit()

    @synchronized
    def purge_expired(self, retention_days):
        with self.db:
            self.db.execute("DELETE FROM tombstones WHERE forgotten_at < ?",
                            (time.time() - retention_days * 86400,))
            self.db.commit()

    @synchronized
    def purge(self, note_id):
        """硬删：含修订历史（显式操作，区别于 forget 的受管遗忘）。"""
        with self.db:
            self.db.execute("DELETE FROM knowledge WHERE note_id=?", (note_id,))
            self.db.execute("DELETE FROM claims WHERE note_id=?", (note_id,))
            self.db.execute("DELETE FROM revisions WHERE note_id=?", (note_id,))
            self.db.execute("DELETE FROM review_pending WHERE note_id=?", (note_id,))
            self.db.execute("DELETE FROM claim_bindings WHERE note_id=?", (note_id,))
            self.db.commit()

    @synchronized
    def tombstones(self):
        return [{"note_id": r[0], "reason": r[1], "forgotten_at": r[2]}
                for r in self.db.execute(
                    "SELECT note_id, reason, forgotten_at FROM tombstones ORDER BY forgotten_at")]

    # ---------- R07：备份/恢复/Markdown 互操作 ----------
    @synchronized
    def backup(self, out_dir):
        """Publish a new knowledge-only archive; counts describe the backed-up snapshot."""
        out_dir = os.path.abspath(out_dir)
        if os.path.lexists(out_dir):
            raise FileExistsError("backup destination already exists")
        parent = os.path.dirname(out_dir)
        os.makedirs(parent, exist_ok=True)
        staging = tempfile.mkdtemp(prefix=".kb-backup-", dir=parent)
        try:
            dst = os.path.join(staging, "kb.db")
            target = sqlite3.connect(dst)
            try:
                self.db.backup(target)
                counts = _table_counts(target)
            finally:
                target.close()
            manifest = {"schema": "domimap.kbackup.v2", "notes": counts["knowledge"],
                        "revisions": counts["revisions"], "claims": counts["claims"],
                        "table_counts": counts, "sha256": _file_sha(dst), "created": time.time()}
            with open(dst, "rb") as stream:
                os.fsync(stream.fileno())
            with open(os.path.join(staging, "manifest.json"), "w", encoding="utf-8") as stream:
                json.dump(manifest, stream, ensure_ascii=False, indent=1)
                stream.flush()
                os.fsync(stream.fileno())
            sync_directory(staging)
            os.rename(staging, out_dir)
            sync_directory(parent)
            return manifest
        finally:
            if os.path.isdir(staging):
                shutil.rmtree(staging)

    @classmethod
    def restore(cls, backup_dir, db_path):
        """Validate a private staging copy before publishing to a fresh destination."""
        db_path = os.path.abspath(db_path)
        if any(os.path.lexists(db_path + suffix) for suffix in ("", "-wal", "-shm", "-journal")):
            raise FileExistsError("restore requires a new database destination")
        base = os.path.realpath(backup_dir)
        for member in ("kb.db", "manifest.json"):
            p = os.path.join(backup_dir, member)
            real = os.path.realpath(p)
            inside = os.path.commonpath([real, base]) == base  # 解析后仍在归档目录内
            if os.path.islink(p) or not os.path.isfile(real) or not inside:
                raise ValueError("归档成员非法（符号链接/穿越）：%s" % member)
        with open(os.path.join(backup_dir, "manifest.json"), encoding="utf-8") as stream:
            raw_manifest = stream.read((1 << 16) + 1)
        if len(raw_manifest) > (1 << 16):
            raise ValueError("backup manifest exceeds size limit")
        manifest = json.loads(raw_manifest)
        if not isinstance(manifest, dict) or manifest.get("schema") not in {
                "domimap.kbackup.v1", "domimap.kbackup.v2"}:
            raise ValueError("unsupported backup schema")
        parent = os.path.dirname(db_path)
        os.makedirs(parent, exist_ok=True)
        fd, staging = tempfile.mkstemp(prefix=".kb-restore-", dir=parent)
        os.close(fd)
        try:
            shutil.copyfile(os.path.join(backup_dir, "kb.db"), staging)
            if manifest["schema"] == "domimap.kbackup.v2" and _file_sha(staging) != manifest.get("sha256"):
                raise ValueError("backup database hash mismatch")
            source = sqlite3.connect(Path(staging).as_uri() + "?mode=ro", uri=True)
            try:
                counts = _validate_backup_database(source)
            except sqlite3.DatabaseError as error:
                raise ValueError("invalid backup database") from error
            finally:
                source.close()
            for key, table in (("notes", "knowledge"), ("revisions", "revisions"), ("claims", "claims")):
                if type(manifest.get(key)) is not int or manifest[key] != counts[table]:
                    raise ValueError("backup count mismatch: " + key)
            if manifest["schema"] == "domimap.kbackup.v2":
                declared = manifest.get("table_counts")
                if (not isinstance(declared, dict) or declared != counts
                        or any(type(value) is not int for value in declared.values())):
                    raise ValueError("backup table counts mismatch")
            with open(staging, "rb") as stream:
                os.fsync(stream.fileno())
            # Atomic no-clobber publication; unlike replace(), a concurrent creator also wins safely.
            os.link(staging, db_path)
            sync_directory(parent)
            return cls(db_path)
        finally:
            os.unlink(staging)

    @read_snapshot
    def export_markdown(self, out_dir):
        """active 笔记导出为 MD（front-matter: note_id/base_revision/status + claims）。"""
        os.makedirs(out_dir, exist_ok=True)
        paths = []
        for n in self.list_active():
            full = self.get(n["note_id"])
            fm = ["---", "note_id: %s" % n["note_id"], "base_revision: %d" % full["revision"],
                  "status: %s" % full["status"], "claims: %s" % json.dumps(
                      full["claims"], ensure_ascii=False), "---", ""]
            p = os.path.join(out_dir, n["note_id"].replace(":", "_") + ".md")
            with open(p, "w", encoding="utf-8") as f:
                f.write("\n".join(fm) + full["body"])
            paths.append(p)
        return paths

    @synchronized
    def import_markdown(self, path):
        """显式导入：base_revision=当前 → amend 新修订；过期 → ConflictError（防覆盖）。"""
        text = open(path, encoding="utf-8").read()
        if not text.startswith("---"):
            raise ValueError("缺少 front-matter")
        meta, _, body = text.split("---", 2)[1], None, text.split("---", 2)[2].lstrip("\n")
        fields = {}
        for ln in meta.strip().split("\n"):
            if ": " in ln:
                k, _, v = ln.partition(": ")
                fields[k.strip()] = v.strip()
        note_id, base = fields["note_id"], int(fields["base_revision"])
        cur = self.db.execute("SELECT revision FROM knowledge WHERE note_id=? AND status='active'",
                              (note_id,)).fetchone()
        if not cur:
            raise ConflictError("笔记不存在或已撤回: %s" % note_id)
        if cur[0] != base:
            raise ConflictError("base_revision 过期：当前 %d ≠ 文件 %d" % (cur[0], base))
        claims = json.loads(fields.get("claims", "[]")) or None
        return self.amend(note_id, body=body, expected_revision=base, claims=claims)

    @read_snapshot
    def claims_with_flags(self, current_digests=None):
        """检索面 claim 视图：依据已变且未绑定当前版本的 claim 标 stale（F4-02）。"""
        out = {}
        for n in self.list_active():
            fl = []
            for c in n["claims"]:
                c = dict(c)
                if current_digests is not None:
                    c["stale"] = any(
                        ev in current_digests and ev not in c.get("evidence", [])
                        for ev in []) or self._claim_stale(n["note_id"], c, current_digests)
                fl.append(c)
            out[n["note_id"]] = fl
        return out

    def _claim_stale(self, note_id, claim, current):
        bound = self.db.execute(
            "SELECT sha FROM claim_bindings WHERE note_id=? AND claim_idx=?",
            (note_id, claim.get("idx", 0))).fetchone()
        for ev in claim.get("evidence", []):
            if ev in current and bound and current[ev] != bound[0]:
                return True
        return False

    @synchronized
    def count(self):
        return self.db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]

    def _claims_of(self, note_id):
        return [{"idx": r[0], "type": r[1], "statement": r[2], "evidence": json.loads(r[3] or "[]"),
                 "scope": r[4], "state": r[5]}
                for r in self.db.execute(
                    "SELECT idx, type, statement, evidence, scope, state FROM claims "
                    "WHERE note_id=? ORDER BY idx", (note_id,))]

    def _check_claims(self, claims):
        for c in claims:
            if c.get("type") not in CLAIM_TYPES:
                raise ValueError("claim 类型必须是 %s 之一：%r" % (sorted(CLAIM_TYPES), c.get("type")))
        return claims

    @synchronized
    def close(self):
        self.db.close()
