"""observation — 查询可观测性：本地 queries.db 事件记录（retrieval-observation P1）。

闭环首片：只记录，不改变检索排序、拒答判定与任何查询返回语义。
纪律（specs/tasks/retrieval-observation.md）：
- fail-open：记录链路任何异常 → status=recording_failed，查询结果照常返回，不抛出不等待。
- 隐私默认：不存原始查询文本，只存长度/是否 CJK/HMAC-SHA256(查询, 工作区密钥) 摘要；
  显式配置（DOMIMAP_KEEP_QUERIES=1 或调用方 keep_text=True）才本地保留原文。
- 幂等：同 idempotency_key 同内容 → duplicate；同键异内容 → conflict（原事件不动，不覆盖）。
- 有界：单事务写入 + 固定容量裁剪（MAX_EVENTS），无后台队列。
"""
import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time

from .storage import synchronized

OBS_SCHEMA = "domimap.obs.v1"
MAX_EVENTS = 20000
# 记录延迟上界（F09）：单次锁等待 1s × 至多 3 次尝试 ≈ 3s；超界即 recording_failed，
# 不让观测写入同步拖长查询返回（fail-open）
BUSY_TIMEOUT_MS = 1000
RECORD_ATTEMPTS = 3
RECORD_LATENCY_BOUND_S = 4.0

STATUS_VALUES = ("ok", "refused", "error", "cancelled")
TRIGGER_VALUES = ("user", "retry", "replay", "diagnostic")
ENTRY_VALUES = ("cli", "mcp", "ui")
# 与 domimap/search.py 拒答分支一一对应；消费方不得从中文文案反推原因
REFUSAL_REASONS = ("identifier_absent", "empty_query", "generic_only",
                   "coverage_below_min", "domain_filter_empty", "no_strong_candidate")

SCHEMA = """
CREATE TABLE IF NOT EXISTS query_events (
  event_id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL,
  parent_event_id TEXT,
  entry TEXT NOT NULL,
  trigger_kind TEXT NOT NULL,
  created REAL NOT NULL,
  query_digest TEXT NOT NULL,
  query_len INTEGER NOT NULL,
  query_has_cjk INTEGER NOT NULL,
  query_text TEXT,
  params_json TEXT NOT NULL,
  version_json TEXT NOT NULL,
  status TEXT NOT NULL,
  refusal_reason TEXT,
  cov REAL,
  min_cov REAL,
  result_json TEXT NOT NULL,
  idempotency_key TEXT UNIQUE,
  content_digest TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS idempotency_conflicts (
  key TEXT NOT NULL, content_digest TEXT NOT NULL, created REAL NOT NULL,
  PRIMARY KEY (key, content_digest));
CREATE INDEX IF NOT EXISTS idx_query_events_created ON query_events(created);
CREATE INDEX IF NOT EXISTS idx_query_events_request ON query_events(request_id);
"""

_failed = {"event_id": None, "status": "recording_failed"}


def observation_enabled():
    """DOMIMAP_OBSERVE=0 完全关闭（不建库不写）；默认开启。"""
    return os.environ.get("DOMIMAP_OBSERVE", "1") != "0"


def keep_text_default():
    return os.environ.get("DOMIMAP_KEEP_QUERIES", "") == "1"


def _canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def workspace_key(ws_dir):
    """工作区密钥（queries.key，0600，O_EXCL 原子创建）：HMAC 摘要用，普通哈希不保证隐私。

    F09 纠正：并发首次创建时用 O_CREAT|O_EXCL 定胜负——赢家唯一且永不被覆盖；
    输家读取赢家密钥（短暂重试覆盖"已创建未写完"窗口）。
    """
    path = os.path.join(ws_dir, "queries.key")
    try:
        with open(path, "rb") as f:
            key = f.read()
        if key:
            return key
    except OSError:
        pass
    key = os.urandom(32)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        for _ in range(200):  # ≤2s：等待赢家写完
            try:
                with open(path, "rb") as f:
                    winner = f.read()
                if winner:
                    return winner
            except OSError:
                pass
            time.sleep(0.01)
        raise OSError("workspace key creation race: winner never completed")
    with os.fdopen(fd, "wb") as f:
        f.write(key)
        f.flush()
        os.fsync(f.fileno())
    return key


# 查询签名的有效默认（与 Searcher.query 形参默认一致；事件记录实际生效值）
_QUERY_DEFAULTS = {"top_k": 6, "expand": True, "min_cov": 0.3, "budget": 3800}


def collect_version(searcher, graph_path):
    """版本指纹（F06 纠正）：程序版本 + 图签名 + 节点数 + 索引 schema + 知识代际 +
    种子词表摘要；取不到的值为 unknown，不伪造可复现性。"""
    from . import __version__
    from .search import IDX_SCHEMA
    sig = getattr(getattr(searcher, "g", None), "sig", None) or {}
    nodes = len(searcher.g.nodes) if getattr(searcher, "g", None) is not None else None
    try:
        st = os.stat(graph_path)
        mt, sz = st.st_mtime, st.st_size
    except OSError:
        mt = sz = None
    knowledge = "unknown"
    kb = os.path.join(os.path.dirname(os.path.abspath(graph_path)), "knowledge.db")
    try:
        kst = os.stat(kb)
        knowledge = {"mtime": kst.st_mtime, "size": kst.st_size}
    except OSError:
        pass
    seeds_sha = "unknown"
    try:
        h = hashlib.sha256()
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "seeds.json"), "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        seeds_sha = h.hexdigest()
    except OSError:
        pass
    return {"domimap": __version__,
            "graph_mtime": sig.get("mtime", mt) if sig.get("mtime") is not None else mt,
            "graph_size": sig.get("size", sz) if sig.get("size") is not None else sz,
            "nodes": nodes,
            "idx_schema": IDX_SCHEMA,
            "knowledge": knowledge,
            "seeds_sha256": seeds_sha}


def observe_result(r, error=None):
    """从查询返回提取结果观测：有序候选（顺序即名次）、计数与可选层信息；不解析文案。"""
    seeds = r.get("seeds") or []
    obs = {"candidates": [{"id": n["id"], "kind": n["kind"], "file": n["file"]}
                          for n in seeds],
           "candidate_count": len(seeds),
           "expanded_count": r.get("expanded_count"),
           "semantic_bridge": r.get("semantic_bridge"),
           "embedding": r.get("embedding"),
           "llm_rerank": r.get("llm_rerank"),
           "coverage": r.get("coverage")}
    if error is not None:
        obs["error"] = error
    return obs


class ObservationStore:
    """短连接 SQLite 记录库；record 为唯一写入口（进程内锁 + SQLite 锁双保险）。"""

    def __init__(self, db_path):
        self.db_path = db_path
        self._lock = threading.RLock()
        self.db = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_MS / 1000.0,
                                  check_same_thread=False)
        self.db.execute("PRAGMA busy_timeout=%d" % BUSY_TIMEOUT_MS)
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass  # 并发初始化时可短暂忙；WAL 持久化于库文件，晚到连接照常工作
        self._init_schema()

    def _init_schema(self):
        for attempt in range(RECORD_ATTEMPTS):
            try:
                self.db.executescript(SCHEMA)
                self.db.commit()
                return
            except sqlite3.OperationalError as error:
                if "locked" not in str(error) or attempt == 2:
                    raise
                time.sleep(0.02 * (attempt + 1))

    @synchronized
    def record(self, *, event_id, request_id, parent_event_id, entry, trigger_kind,
               query_digest, query_len, query_has_cjk, query_text, params, version,
               status, refusal_reason, cov, min_cov, result, idempotency_key,
               content_digest):
        # WAL 下并发写可能短暂 busy：有界重试（3 次×退避），仍失败则上抛 → recording_failed
        for attempt in range(RECORD_ATTEMPTS):
            try:
                return self._record_once(
                    event_id=event_id, request_id=request_id,
                    parent_event_id=parent_event_id, entry=entry,
                    trigger_kind=trigger_kind, query_digest=query_digest,
                    query_len=query_len, query_has_cjk=query_has_cjk,
                    query_text=query_text, params=params, version=version,
                    status=status, refusal_reason=refusal_reason, cov=cov,
                    min_cov=min_cov, result=result, idempotency_key=idempotency_key,
                    content_digest=content_digest)
            except sqlite3.OperationalError as error:
                if "locked" not in str(error) or attempt == 2:
                    raise
                time.sleep(0.02 * (attempt + 1))

    def _record_once(self, **kw):
        event_id = kw["event_id"]
        idempotency_key = kw["idempotency_key"]
        content_digest = kw["content_digest"]
        try:
            with self.db:
                self.db.execute(
                    "INSERT INTO query_events (event_id, request_id, parent_event_id, entry,"
                    " trigger_kind, created, query_digest, query_len, query_has_cjk,"
                    " query_text, params_json, version_json, status, refusal_reason, cov,"
                    " min_cov, result_json, idempotency_key, content_digest)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (event_id, kw["request_id"], kw["parent_event_id"], kw["entry"],
                     kw["trigger_kind"], time.time(), kw["query_digest"],
                     kw["query_len"], int(kw["query_has_cjk"]), kw["query_text"],
                     _canonical(kw["params"]), _canonical(kw["version"]), kw["status"],
                     kw["refusal_reason"], kw["cov"], kw["min_cov"],
                     _canonical(kw["result"]), idempotency_key, content_digest))
        except sqlite3.IntegrityError:
            row = self.db.execute(
                "SELECT event_id, content_digest FROM query_events WHERE idempotency_key=?",
                (idempotency_key,)).fetchone()
            if row and row[1] == content_digest:
                return {"event_id": row[0], "status": "duplicate"}
            with self.db:
                self.db.execute(
                    "INSERT OR IGNORE INTO idempotency_conflicts VALUES (?,?,?)",
                    (idempotency_key, content_digest, time.time()))
            return {"event_id": row[0] if row else None, "status": "conflict"}
        # 容量裁剪（F08 纠正）：有判定反馈/簇关联/诊断的事件豁免（固定证据不毁坏）；
        # 只裁未判定观察，且不会留下孤儿反馈/诊断（被保护者不删，未保护者无派生行）
        with self.db:
            guards = ["NOT EXISTS (SELECT 1 FROM %s x WHERE x.event_id=e.event_id)"
                      % tbl for tbl in ("feedback", "cluster_events", "diagnoses")
                      if self._table_exists(tbl)]
            if guards:
                self.db.execute(
                    "DELETE FROM query_events WHERE event_id IN ("
                    " SELECT event_id FROM (SELECT e.event_id FROM query_events e WHERE "
                    + " AND ".join(guards) +
                    " ORDER BY e.created DESC, e.rowid DESC LIMIT -1 OFFSET ?))",
                    (MAX_EVENTS,))
            else:
                self.db.execute(
                    "DELETE FROM query_events WHERE event_id NOT IN "
                    "(SELECT event_id FROM query_events ORDER BY created DESC,"
                    " rowid DESC LIMIT ?)", (MAX_EVENTS,))
        return {"event_id": event_id, "status": "recorded"}

    def _table_exists(self, name):
        return bool(self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,)).fetchone())

    @synchronized
    def close(self):
        self.db.close()


class Recorder:
    """面向入口的记录门面：构造与记录全部 fail-open，永不抛出、永不阻塞查询。"""

    def __init__(self, graph_path):
        self.ws = os.path.dirname(os.path.abspath(graph_path))
        self.db_path = os.path.join(self.ws, "queries.db")
        self.graph_path = graph_path
        self._key = None

    def _hmac(self, text):
        if self._key is None:
            self._key = workspace_key(self.ws)
        return hmac.new(self._key, text.encode("utf-8"), hashlib.sha256).hexdigest()

    def record_query(self, *, entry, text, params, version, status,
                     refusal_reason=None, cov=None, min_cov=None, result=None,
                     request_id=None, parent_event_id=None, trigger_kind="user",
                     idempotency_key=None, keep_text=None, error=None):
        if entry not in ENTRY_VALUES or trigger_kind not in TRIGGER_VALUES \
                or status not in STATUS_VALUES:
            return dict(_failed)
        if refusal_reason is not None and refusal_reason not in REFUSAL_REASONS:
            return dict(_failed)
        digest = self._hmac(text)
        keep = keep_text if keep_text is not None else keep_text_default()
        has_cjk = any(ord(c) > 0x2E7F for c in text)
        # F09 纠正：请求身份摘要 = 逻辑输入（entry/摘要/有效参数/版本/状态/原因/候选），
        # 排除 duration_ms 等测量噪声——耗时不得决定两次请求是否"相同"。
        effective = dict(_QUERY_DEFAULTS)
        effective.update(params or {})
        identity_result = {k: v for k, v in (result or {}).items()
                           if k != "duration_ms"}
        content = {"entry": entry, "query_digest": digest, "params": effective,
                   "version": version, "status": status,
                   "refusal_reason": refusal_reason, "result": identity_result}
        content_digest = hashlib.sha256(_canonical(content).encode("utf-8")).hexdigest()
        if idempotency_key:
            event_id = "qe:" + hashlib.sha256(
                ("idem:" + idempotency_key).encode("utf-8")).hexdigest()[:24]
        else:
            event_id = "qe:" + hashlib.sha256(os.urandom(24)).hexdigest()[:24]
        store = ObservationStore(self.db_path)
        try:
            return store.record(
                event_id=event_id,
                request_id=request_id or event_id,
                parent_event_id=parent_event_id,
                entry=entry, trigger_kind=trigger_kind,
                query_digest=digest, query_len=len(text), query_has_cjk=has_cjk,
                query_text=text if keep else None,
                params=effective, version=version, status=status,
                refusal_reason=refusal_reason, cov=cov, min_cov=min_cov,
                result=result if result is not None else {},
                idempotency_key=idempotency_key,
                content_digest=content_digest)
        finally:
            store.close()


def record_safely(recorder, **kwargs):
    """唯一允许的记录调用形态：任何异常 → recording_failed，不冒充成功。"""
    try:
        if not observation_enabled():
            return {"event_id": None, "status": "disabled"}
        return recorder.record_query(**kwargs)
    except Exception:
        return dict(_failed)


def _params_for_record(params):
    """记录用参数副本：seeds 域词表只记 provided 标记（词表本身进版本指纹以外的体积控制）。"""
    out = {}
    for k, v in params.items():
        out[k] = {"__provided__": True} if k == "seeds" and isinstance(v, dict) else v
    return out


def run_query(graph_path, searcher, text, entry, params, trigger_kind="user",
              request_id=None, parent_event_id=None, idempotency_key=None,
              keep_text=None):
    """三入口共用包装：执行查询并记录；查询异常先记 error 事件再原样上抛。

    返回 (result, obs)。obs.status ∈ recorded|duplicate|conflict|recording_failed|disabled。
    """
    recorder = Recorder(graph_path)
    version = collect_version(searcher, graph_path)
    params_recorded = _params_for_record(params)
    t0 = time.perf_counter()
    try:
        r = searcher.query(text, **params)
    except Exception as error:
        record_safely(recorder, entry=entry, text=text, params=params_recorded,
                      version=version, status="error",
                      result=observe_result({}, error=type(error).__name__),
                      trigger_kind=trigger_kind, request_id=request_id,
                      parent_event_id=parent_event_id, idempotency_key=idempotency_key,
                      keep_text=keep_text)
        raise
    duration_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    result = observe_result(r)
    result["duration_ms"] = duration_ms
    refused = bool(r.get("refused"))
    obs = record_safely(
        recorder, entry=entry, text=text, params=params_recorded, version=version,
        status="refused" if refused else "ok",
        refusal_reason=r.get("refusal_reason") if refused else None,
        cov=r.get("cov") if refused else None,
        min_cov=r.get("min_cov") if refused else None,
        result=result, trigger_kind=trigger_kind, request_id=request_id,
        parent_event_id=parent_event_id, idempotency_key=idempotency_key,
        keep_text=keep_text)
    return r, obs
