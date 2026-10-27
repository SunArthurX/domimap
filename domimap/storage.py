"""Small connection-ownership primitives shared by the two local SQLite stores."""
import os
from functools import wraps


def synchronized(method):
    """Serialize the complete operation, not just individual SQLite statements."""
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return call


def read_snapshot(method):
    """Keep multi-statement reads consistent, including nested reads in a write transaction."""
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            owns_transaction = not self.db.in_transaction
            if owns_transaction:
                self.db.execute("BEGIN")
            try:
                result = method(self, *args, **kwargs)
                if owns_transaction:
                    self.db.commit()
                return result
            except BaseException:
                if owns_transaction:
                    self.db.rollback()
                raise
    return call


STORE_DB_VERSION = 1       # store.db（证据/代/来源登记/可信根）
KNOWLEDGE_DB_VERSION = 1   # knowledge.db（人工知识；2026-10-26 含 review_pending.new_evkey）
QUERIES_DB_VERSION = 1     # queries.db（观测/反馈/诊断/回放）


def ensure_user_version(db, expected, label):
    """按 PRAGMA user_version 守卫 SQLite 格式版本：0（新建或旧库）→ 打上当前版本；
    低于当前 → 由各库的 CREATE IF NOT EXISTS/ALTER 补齐后打上当前版本；高于当前 → 拒绝打开（fail-safe，不猜）。"""
    current = db.execute("PRAGMA user_version").fetchone()[0]
    if current > expected:
        raise ValueError("%s was written by a newer domimap (user_version %d > %d); upgrade domimap instead of opening it"
                         % (label, current, expected))
    if current != expected:
        db.execute("PRAGMA user_version=%d" % expected)
        db.commit()
    return expected


def sync_directory(path):
    """Persist directory entries on POSIX; Windows has no directory fsync in this API."""
    if os.name == "posix":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
