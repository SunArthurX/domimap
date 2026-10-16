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
import sqlite3
import time
import uuid

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
"""

CLAIM_TYPES = {"requirement", "implementation", "observation", "decision", "inference"}


class ConflictError(ValueError):
    """幂等键内容不一致 / expected_revision 过期。"""


class KnowledgeStore:
    def __init__(self, db_path):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.db = sqlite3.connect(db_path, timeout=30)
        self.db.executescript(SCHEMA)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.commit()
        self._fail_stage = None

    # ---- 内部：短事务包装 ----
    def _tx(self):
        self.db.execute("BEGIN IMMEDIATE")
        return self.db

    def _content_sha(self, body, claims):
        return hashlib.sha256(json.dumps(
            {"body": body, "claims": claims}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def _snapshot(self, note_id, body, claims, revision):
        self.db.execute("INSERT OR REPLACE INTO revisions VALUES (?,?,?,?)",
                        (note_id, revision, json.dumps(
                            {"body": body, "claims": claims}, ensure_ascii=False), time.time()))

    # ---- API ----
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

    def withdraw(self, note_id):
        with self.db:
            self.db.execute("UPDATE knowledge SET status='withdrawn', updated=? WHERE note_id=?",
                            (time.time(), note_id))
            self.db.commit()

    def accept_claim(self, note_id, idx):
        with self.db:
            self.db.execute("UPDATE claims SET state='accepted' WHERE note_id=? AND idx=?",
                            (note_id, idx))
            self.db.commit()

    def get(self, note_id):
        row = self.db.execute(
            "SELECT note_id, body, revision, status FROM knowledge WHERE note_id=?",
            (note_id,)).fetchone()
        if not row:
            return None
        return {"note_id": row[0], "body": row[1], "revision": row[2], "status": row[3],
                "claims": self._claims_of(note_id)}

    def history(self, note_id):
        return [{"revision": r[0], "snapshot": json.loads(r[1]), "created": r[2]}
                for r in self.db.execute(
                    "SELECT revision, snapshot, created FROM revisions WHERE note_id=? "
                    "ORDER BY revision", (note_id,))]

    def list_active(self):
        return [{"note_id": r[0], "body": r[1], "updated": r[2], "claims": self._claims_of(r[0])}
                for r in self.db.execute(
                    "SELECT note_id, body, updated FROM knowledge WHERE status='active' "
                    "ORDER BY updated DESC")]

    def count(self):
        return self.db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]

    def _claims_of(self, note_id):
        return [{"type": r[0], "statement": r[1], "evidence": json.loads(r[2] or "[]"),
                 "scope": r[3], "state": r[4]}
                for r in self.db.execute(
                    "SELECT type, statement, evidence, scope, state FROM claims "
                    "WHERE note_id=? ORDER BY idx", (note_id,))]

    def _check_claims(self, claims):
        for c in claims:
            if c.get("type") not in CLAIM_TYPES:
                raise ValueError("claim 类型必须是 %s 之一：%r" % (sorted(CLAIM_TYPES), c.get("type")))
        return claims

    def close(self):
        self.db.close()
