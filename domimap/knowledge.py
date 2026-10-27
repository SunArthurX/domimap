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

from .storage import synchronized, read_snapshot, sync_directory, ensure_user_version, KNOWLEDGE_DB_VERSION

USER_VERSION = KNOWLEDGE_DB_VERSION

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
  new_evkey TEXT,  -- 2026-10-26：同来源最新证据 ID，确认时直接绑定（旧库由 __init__ ALTER 补列）
  PRIMARY KEY (note_id, claim_idx, new_sha));
CREATE TABLE IF NOT EXISTS claim_bindings (
  note_id TEXT, claim_idx INTEGER, sha TEXT, confirmed_at REAL,
  PRIMARY KEY (note_id, claim_idx));
CREATE TABLE IF NOT EXISTS usage (
  note_id TEXT PRIMARY KEY, hits INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS review_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, note_id TEXT, claim_idx INTEGER,
  action TEXT, statement TEXT, expected_revision INTEGER, auditor TEXT,
  reason TEXT, at REAL);  -- 审定/撤回审计事件（RV03）；不进 BACKUP_TABLES（v2 兼容），见任务规格
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
            actual, expected = db.execute(statement).fetchall(), reference.execute(statement).fetchall()
            if actual != expected:
                # 2026-10-26 之前的 v2 归档：review_pending 无 new_evkey 列；恢复后由 __init__ 补列
                legacy = [row for row in expected if row[1] != "new_evkey"]
                if not (table == "review_pending" and actual == legacy):
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
    ws = os.path.dirname(os.path.abspath(graph_path))
    path = os.path.join(ws, "knowledge.db")
    if not os.path.exists(path):
        return False
    digests = None
    store_db = os.path.join(ws, "store.db")
    if os.path.exists(store_db):  # 依据已变的陈述在检索面标 stale（F4-02 / R06-02）
        from .store import EvidenceStore
        st = EvidenceStore(store_db)
        try:
            digests = st.review_digests()["current"]
        finally:
            st.close()
    kb = KnowledgeStore(path)
    try:
        searcher.attach_knowledge(kb, current_digests=digests)
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
        try:  # 2026-10-26：待复核项记录可绑定的新证据 ID（旧库原地补列；T15 引入 user_version 后改为迁移）
            self.db.execute("ALTER TABLE review_pending ADD COLUMN new_evkey TEXT")
        except sqlite3.OperationalError:
            pass
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.commit()
        ensure_user_version(self.db, USER_VERSION, "knowledge.db")
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
                # claims 重排后旧绑定/待复核按 idx 已无意义：清掉，避免错位绑定压制复核
                self.db.execute("DELETE FROM claim_bindings WHERE note_id=?", (note_id,))
                self.db.execute("DELETE FROM review_pending WHERE note_id=?", (note_id,))
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
    def withdraw(self, note_id, auditor="human:local", reason=""):
        """撤回 active 笔记；不存在或已撤回 → ConflictError（不静默成功）。追加审计事件。"""
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            cur = self.db.execute(
                "UPDATE knowledge SET status='withdrawn', updated=? WHERE note_id=? AND status='active'",
                (time.time(), note_id))
            if cur.rowcount != 1:
                raise ConflictError("知识不存在或已撤回: %s" % note_id)
            self._audit(note_id, None, "withdraw", None, None, auditor, reason)
            self.db.commit()
        return {"note_id": note_id, "status": "withdrawn"}

    def _audit(self, note_id, claim_idx, action, statement, expected_revision, auditor, reason):
        self.db.execute(
            "INSERT INTO review_events (note_id, claim_idx, action, statement,"
            " expected_revision, auditor, reason, at) VALUES (?,?,?,?,?,?,?,?)",
            (note_id, claim_idx, action, statement, expected_revision,
             auditor or "unknown", reason or "", time.time()))

    def review_events(self, note_id):
        return [{"id": r[0], "claim_idx": r[1], "action": r[2], "statement": r[3],
                 "expected_revision": r[4], "auditor": r[5], "reason": r[6], "at": r[7]}
                for r in self.db.execute(
                    "SELECT id, claim_idx, action, statement, expected_revision, auditor,"
                    " reason, at FROM review_events WHERE note_id=? ORDER BY id", (note_id,))]

    @synchronized
    def accept_claim(self, note_id, idx, expected_revision=None, statement=None,
                     auditor="human:local", reason=""):
        """审定一条陈述为 accepted（RV03：绑定 expected_revision + 陈述身份，事务内校验并追加审计事件）。

        只改状态，不改类型：推断被接受仍是推断。旧式无绑定调用（expected_revision/statement 缺省）
        一律 TypeError 拒绝——防止"看过 A、批准了 B"。撤回后的笔记不可审定。
        """
        if expected_revision is None or statement is None:
            raise TypeError("accept_claim 需要显式 expected_revision 与 statement（审定绑定，RV03）")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute(
                "SELECT k.revision, k.status, c.statement, c.state FROM knowledge k"
                " JOIN claims c ON c.note_id=k.note_id AND c.idx=? WHERE k.note_id=?",
                (idx, note_id)).fetchone()
            if not row:
                raise ConflictError("陈述不存在: %s#%s" % (note_id, idx))
            revision, status, current_statement, _ = row
            if status != "active":
                raise ConflictError("笔记已撤回，不可审定: %s" % note_id)
            if revision != expected_revision:
                raise ConflictError(
                    "审定绑定的修订过期：当前 %d ≠ 请求 %d（内容可能已被他人修改）"
                    % (revision, expected_revision))
            if (current_statement or "").strip() != statement.strip():
                raise ConflictError(
                    "审定绑定的陈述不符：当前为 %r ≠ 请求 %r" % (current_statement, statement))
            self.db.execute("UPDATE claims SET state='accepted' WHERE note_id=? AND idx=?",
                            (note_id, idx))
            self._audit(note_id, idx, "accept", current_statement, expected_revision,
                        auditor, reason)
            self.db.commit()
        return {"note_id": note_id, "idx": idx, "state": "accepted",
                "revision": expected_revision, "auditor": auditor}

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
    def record_baseline(self, current, overwrite=True):
        """登记证据键基线摘要。overwrite=False 时只补缺（引用时的版本即基线，不被后续扫描推进）。"""
        verb = "INSERT OR REPLACE" if overwrite else "INSERT OR IGNORE"
        with self.db:
            for key, sha in current.items():
                self.db.execute(verb + " INTO baselines VALUES (?,?,?)", (key, sha, time.time()))

    @synchronized
    def scan_dependencies(self, current, latest_keys=None):
        """当前摘要 vs 基线：仅受影响 claim 入待复核队列（幂等，主键去重）。

        latest_keys: evkey → 同来源最新证据 ID（确认时可直接绑定）。
        点击/使用频率不参与（真实性只由确认绑定或修改/撤回改变）。
        """
        latest_keys = latest_keys or {}
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            old = {r[0]: r[1] for r in self.db.execute("SELECT evkey, sha FROM baselines")}
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
                                "INSERT OR IGNORE INTO review_pending "
                                "(note_id, claim_idx, evkey, old_sha, new_sha, since, new_evkey) VALUES (?,?,?,?,?,?,?)",
                                (note_id, idx, evkey, old[evkey], current[evkey], time.time(),
                                 latest_keys.get(evkey)))
            self.db.commit()
            return self.review_queue()

    def review_queue(self):
        """待复核队列（含陈述原文与可绑定的新证据 ID）。"""
        rows = self.db.execute(
            "SELECT p.note_id, p.claim_idx, p.evkey, p.old_sha, p.new_sha, p.new_evkey, p.since, c.statement "
            "FROM review_pending p LEFT JOIN claims c ON c.note_id=p.note_id AND c.idx=p.claim_idx "
            "ORDER BY p.since, p.note_id, p.claim_idx").fetchall()
        return [{"note_id": r[0], "claim_idx": r[1], "evidence": r[2], "old_sha": r[3], "new_sha": r[4],
                 "new_evidence": r[5], "since": r[6], "statement": r[7],
                 "actions": ["confirm(绑定新证据)", "amend(修改)", "withdraw(撤回)"]} for r in rows]

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

    @staticmethod
    def _parse_export(text):
        """解析导出页 front-matter（note_id/base_revision/status/claims）与正文。"""
        if not text.startswith("---"):
            raise ValueError("缺少 front-matter")
        parts = text.split("---", 2)
        if len(parts) < 3:
            raise ValueError("front-matter 未闭合")
        fields = {}
        for ln in parts[1].strip().split("\n"):
            if ": " in ln:
                k, _, v = ln.partition(": ")
                fields[k.strip()] = v.strip()
        if "note_id" not in fields or "base_revision" not in fields:
            raise ValueError("不是知识导出页（缺 note_id/base_revision）")
        return fields, parts[2].lstrip("\n")

    @read_snapshot
    def preview_import(self, path):
        """导入前预览（R07-02 冲突可预览）：库内当前正文/修订 vs 文件 base_revision/正文；不写库。"""
        with open(path, encoding="utf-8") as f:
            fields, body = self._parse_export(f.read())
        note_id, base = fields["note_id"], int(fields["base_revision"])
        cur = self.db.execute("SELECT body, revision, status FROM knowledge WHERE note_id=?",
                              (note_id,)).fetchone()
        exists = bool(cur) and cur[2] == "active"
        current_rev = cur[1] if cur else None
        return {"note_id": note_id, "exists": exists, "status": cur[2] if cur else None,
                "file_revision": base, "current_revision": current_rev,
                "revisions_ahead": (current_rev - base) if current_rev is not None else None,
                "conflict": (not exists) or current_rev != base,
                "current_body": cur[0] if cur else None, "file_body": body,
                "claims": json.loads(fields.get("claims", "[]"))}

    @synchronized
    def import_markdown(self, path):
        """显式导入：base_revision=当前 → amend 新修订；过期 → ConflictError（防覆盖）。"""
        with open(path, encoding="utf-8") as f:
            fields, body = self._parse_export(f.read())
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
        """陈旧 = 待复核队列里有它，或已确认绑定的版本不是来源当前版本（点击/重建都不清除）。"""
        idx = claim.get("idx", 0)
        if self.db.execute("SELECT 1 FROM review_pending WHERE note_id=? AND claim_idx=? LIMIT 1",
                           (note_id, idx)).fetchone():
            return True
        bound = self.db.execute(
            "SELECT sha FROM claim_bindings WHERE note_id=? AND claim_idx=?", (note_id, idx)).fetchone()
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
