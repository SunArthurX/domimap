"""graph.db — 图的 SQLite 副本。节点一次载入，边按端点查询，避免把全部边装进内存。"""
import json
import os
import sqlite3
import tempfile
import threading

from .storage import ensure_user_version

GRAPH_DB_VERSION = 1

_SCHEMA = """
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    file TEXT NOT NULL,
    meta TEXT NOT NULL,
    conf TEXT NOT NULL,
    prov TEXT NOT NULL
);
CREATE TABLE edges (
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    kind TEXT NOT NULL,
    conf TEXT NOT NULL,
    prov TEXT NOT NULL
);
CREATE INDEX edges_src ON edges(src);
CREATE INDEX edges_dst ON edges(dst);
CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
"""


def write_graph_db(g, path, source_size=None, source_mtime_ns=None):
    """把当前内存图写成 graph.db。先写临时文件，完成后 replace。"""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".graph.db.", dir=directory)
    os.close(fd)
    try:
        conn = sqlite3.connect(tmp)
        try:
            conn.execute("PRAGMA journal_mode=OFF")
            conn.execute("PRAGMA synchronous=OFF")
            conn.executescript(_SCHEMA)
            conn.executemany(
                "INSERT INTO nodes VALUES (?,?,?,?,?,?,?)",
                ((n["id"], n["kind"], n["name"], n["file"],
                  json.dumps(n.get("meta") or {}, ensure_ascii=False),
                  n.get("conf") or "", n.get("prov") or "")
                 for n in g.nodes.values()))
            conn.executemany(
                "INSERT INTO edges VALUES (?,?,?,?,?)",
                ((e["src"], e["dst"], e["kind"], e.get("conf") or "", e.get("prov") or "")
                 for e in g.edges))
            if source_size is not None:
                conn.execute("INSERT INTO meta VALUES ('source_size', ?)", (str(source_size),))
                conn.execute("INSERT INTO meta VALUES ('source_mtime_ns', ?)", (str(source_mtime_ns or 0),))
            ensure_user_version(conn, GRAPH_DB_VERSION, "graph.db")
            conn.commit()
        finally:
            conn.close()
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


class EdgeStore:
    """只读图库。连接在 Graph 存活期间保持打开。"""

    def __init__(self, path):
        self.path = path
        self.db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        ensure_user_version(self.db, GRAPH_DB_VERSION, "graph.db")

    def _rows(self, sql, args=()):
        with self._lock:
            return self.db.execute(sql, args).fetchall()

    def matches_file(self, path):
        """graph.json 的大小和 mtime 与写入时一致才使用本库，避免热重载读到旧边。"""
        try:
            st = os.stat(path)
        except OSError:
            return False
        rows = dict(self._rows("SELECT k, v FROM meta"))
        return rows.get("source_size") == str(st.st_size) and rows.get("source_mtime_ns") == str(st.st_mtime_ns)

    def close(self):
        self.db.close()

    def load_nodes(self):
        nodes = {}
        for nid, kind, name, file, meta, conf, prov in self._rows(
                "SELECT id, kind, name, file, meta, conf, prov FROM nodes"):
            nodes[nid] = {"id": nid, "kind": kind, "name": name, "file": file,
                          "meta": json.loads(meta), "conf": conf, "prov": prov}
        return nodes

    def edge_count(self):
        return self._rows("SELECT COUNT(*) FROM edges")[0][0]

    def iter_edges(self):
        for src, dst, kind, conf, prov in self._rows(
                "SELECT src, dst, kind, conf, prov FROM edges ORDER BY rowid"):
            yield {"src": src, "dst": dst, "kind": kind, "conf": conf, "prov": prov}

    def neighbors(self, nid, rev=False):
        if rev:
            rows = self._rows(
                "SELECT src, kind, conf, prov FROM edges WHERE dst=? ORDER BY rowid", (nid,))
            return [{"src": src, "dst": nid, "kind": kind, "conf": conf, "prov": prov}
                    for src, kind, conf, prov in rows]
        rows = self._rows(
            "SELECT dst, kind, conf, prov FROM edges WHERE src=? ORDER BY rowid", (nid,))
        return [{"src": nid, "dst": dst, "kind": kind, "conf": conf, "prov": prov}
                for dst, kind, conf, prov in rows]


class EdgeSeq:
    """len / 迭代走 SQLite，不把边列表放进进程。"""

    def __init__(self, store):
        self.store = store

    def __len__(self):
        return self.store.edge_count()

    def __iter__(self):
        return self.store.iter_edges()
