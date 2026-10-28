"""检索倒排的 SQLite 副本。词表进内存，posting 按查询词读取。"""
import os
import sqlite3
import tempfile
import threading

SCHEMA = "domimap.idx.db.v1"

_DDL = """
CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE df (term TEXT PRIMARY KEY, n INTEGER NOT NULL);
CREATE TABLE postings (term TEXT NOT NULL, nid TEXT NOT NULL, tf INTEGER NOT NULL);
CREATE INDEX postings_term ON postings(term);
CREATE INDEX postings_nid ON postings(nid);
"""


def idxdb_path(cache_path):
    if cache_path.endswith(".idx.json"):
        return cache_path[:-len(".json")] + ".db"
    return cache_path + ".db"


def write_idx_db(path, docs, index, n_docs, avgdl, sig, node_count):
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".idx.db.", dir=directory)
    os.close(fd)
    try:
        conn = sqlite3.connect(tmp)
        try:
            conn.execute("PRAGMA journal_mode=OFF")
            conn.execute("PRAGMA synchronous=OFF")
            conn.executescript(_DDL)
            conn.executemany("INSERT INTO df VALUES (?,?)",
                             ((term, len(ids)) for term, ids in index.items()))
            conn.executemany(
                "INSERT INTO postings VALUES (?,?,?)",
                ((term, nid, tf) for nid, cnt in docs.items() for term, tf in cnt.items()))
            meta = {
                "schema": SCHEMA,
                "graph_mtime": str(sig["mtime"]),
                "graph_size": str(sig["size"]),
                "node_count": str(node_count),
                "N": str(n_docs),
                "avgdl": repr(float(avgdl)),
            }
            conn.executemany("INSERT INTO meta VALUES (?,?)", meta.items())
            conn.commit()
        finally:
            conn.close()
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


class IdxDB:
    def __init__(self, path):
        self.path = path
        self.db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()

    def close(self):
        self.db.close()

    def _all(self, sql, args=()):
        with self._lock:
            return self.db.execute(sql, args).fetchall()

    def meta(self):
        return dict(self._all("SELECT k, v FROM meta"))

    def matches(self, sig, node_count):
        m = self.meta()
        return (m.get("schema") == SCHEMA and sig
                and m.get("graph_mtime") == str(sig.get("mtime"))
                and m.get("graph_size") == str(sig.get("size"))
                and m.get("node_count") == str(node_count))

    def vocabulary(self):
        return dict(self._all("SELECT term, n FROM df"))

    def stats(self):
        m = self.meta()
        return int(m["N"]), float(m["avgdl"])

    def postings(self, term):
        return {row[0] for row in self._all(
            "SELECT nid FROM postings WHERE term=?", (term,))}

    def doc_tf(self, nid):
        return dict(self._all(
            "SELECT term, tf FROM postings WHERE nid=?", (nid,)))


class LazyDocs(dict):
    """按节点取词频。没查过的节点不进内存。"""

    def __init__(self, store):
        super().__init__()
        self.store = store

    def get(self, nid, default=None):
        if nid not in self:
            raw = self.store.doc_tf(nid)
            if not raw:
                return default
            from collections import Counter
            self[nid] = Counter(raw)
        return dict.get(self, nid, default)


class LazyIndex(dict):
    """按词取文档集合。__missing__ 让 attach 时的 index[t].add 先装已有 posting。"""

    def __init__(self, store):
        super().__init__()
        self.store = store

    def __missing__(self, term):
        ids = self.store.postings(term)
        self[term] = ids
        return ids

    def get(self, term, default=None):
        return self[term]
