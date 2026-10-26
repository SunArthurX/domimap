"""replay — 固定样本集回放与基线/候选比较（retrieval-evolution-pilot P4）。

纪律：
- 样本集加载即冻结（sha256 存档）：改样本=新 run，与旧 run 不可比（明确拒绝比较）。
- 每次样本执行以 trigger=replay 记录事件（EV13：不污染真实用户统计）。
- 回放走确定性核心：seeds 保留（生产 CLI 语义），semantic/rerank/embed 可选层剥离。
- 判定：expect=refused → 拒答即通过；expected=证据子串 → 文件级名次 ≤ top_k 通过
  （与 diagnosis 同粒度）。有返回结果不等于命中。
"""
import hashlib
import json
import os
import sqlite3
import time

REPLAY_SCHEMA = """
CREATE TABLE IF NOT EXISTS replay_runs (
  run_id TEXT PRIMARY KEY,
  created REAL NOT NULL,
  label TEXT NOT NULL,
  source_fingerprint TEXT,
  samples_sha256 TEXT NOT NULL,
  params_json TEXT NOT NULL,
  results_json TEXT NOT NULL,
  summary_json TEXT NOT NULL,
  notes TEXT);
CREATE TABLE IF NOT EXISTS replay_cluster_links (
  run_id TEXT NOT NULL,
  cluster_id TEXT NOT NULL,
  PRIMARY KEY (run_id, cluster_id));
CREATE TABLE IF NOT EXISTS improvements (
  improvement_id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL,
  diagnosis_id TEXT,
  baseline_run TEXT NOT NULL,
  candidate_run TEXT NOT NULL,
  rollback_run TEXT,
  decision TEXT NOT NULL,
  decided_at REAL NOT NULL,
  source_fingerprint TEXT,
  notes TEXT);
CREATE INDEX IF NOT EXISTS idx_improvements_cluster ON improvements(cluster_id);
"""

BUSY_TIMEOUT_MS = 5000


def _canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loop_connect(db_path):
    """完整闭环 schema 连接（record_improvement/chain 需要簇与诊断表）。"""
    from .feedback import _loop_schema_sql
    db = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_MS / 1000.0,
                         check_same_thread=False)
    db.execute("PRAGMA busy_timeout=%d" % BUSY_TIMEOUT_MS)
    try:
        db.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass
    for attempt in range(3):
        try:
            db.executescript(_loop_schema_sql())
            db.commit()
            break
        except sqlite3.OperationalError as error:
            if "locked" not in str(error) or attempt == 2:
                raise
            time.sleep(0.02 * (attempt + 1))
    return db


def _connect(db_path):
    db = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_MS / 1000.0,
                         check_same_thread=False)
    db.execute("PRAGMA busy_timeout=%d" % BUSY_TIMEOUT_MS)
    try:
        db.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass
    for attempt in range(3):
        try:
            db.executescript(REPLAY_SCHEMA)
            db.commit()
            break
        except sqlite3.OperationalError as error:
            if "locked" not in str(error) or attempt == 2:
                raise
            time.sleep(0.02 * (attempt + 1))
    return db


RUNNER_VERSION = "domimap.replay.v2"
SCORER_VERSION = "exact-node-v1"
# 冻结维度：两次 run 可比较必须在这些维度一致（代码指纹按设计允许基线/候选不同）
FROZEN_DIMENSIONS = ("runner", "scorer", "samples_sha256", "graph", "knowledge",
                     "seeds_sha256")


def load_samples(path):
    """读样本文件并计算冻结摘要；结构不合法立即失败（不静默修样本）。

    F02 纠正：期望必须是精确节点身份——expect="refused" 或
    expect={"node": "<精确节点ID>"} / {"nodes": ["<id>", ...]}（可接受证据组）。
    旧的名称/路径子串（"expected" 字段）一律拒绝并明确 deprecated，不得作为 gold。
    """
    with open(path, "rb") as f:
        raw = f.read()
    sha = hashlib.sha256(raw).hexdigest()
    data = json.loads(raw.decode("utf-8"))
    samples = data.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("样本文件必须是非空 samples 数组")
    seen = set()
    for s in samples:
        if not isinstance(s, dict) or not isinstance(s.get("id"), str) \
                or not isinstance(s.get("query"), str) or not s["query"].strip():
            raise ValueError("样本缺少 id/query")
        if s["id"] in seen:
            raise ValueError("样本 id 重复：%s" % s["id"])
        seen.add(s["id"])
        if "expected" in s:
            raise ValueError(
                "样本 %s 使用已废弃的名称/路径子串 gold（expected=%r）：文件级子串"
                "会把同文件错误节点算成命中。请改为 expect={'node': '<精确节点ID>'}"
                " 或 {'nodes': [...]}，或 expect='refused'" % (s["id"], s["expected"]))
        expect = s.get("expect")
        if expect == "refused":
            continue
        if isinstance(expect, dict):
            nodes = [expect["node"]] if isinstance(expect.get("node"), str) \
                else expect.get("nodes")
            if isinstance(nodes, list) and nodes and all(
                    isinstance(n, str) and n.strip() for n in nodes):
                continue
        raise ValueError(
            "样本 %s 必须指明 expect='refused' 或 expect={'node'/'nodes' 精确节点ID}"
            % s["id"])
    return samples, sha


def _expect_nodes(sample):
    expect = sample.get("expect")
    if expect == "refused":
        return None
    if "expected" in sample:
        raise ValueError(
            "样本 %s 使用已废弃的子串 gold（expected=%r）：须为精确节点身份"
            % (sample.get("id"), sample["expected"]))
    if not isinstance(expect, dict):
        raise ValueError(
            "样本 %s 缺少合法 expect（'refused' 或 {'node'/'nodes'}）"
            % sample.get("id"))
    if isinstance(expect.get("node"), str):
        return {expect["node"]}
    nodes = set(expect.get("nodes") or [])
    if not nodes:
        raise ValueError("样本 %s 的 nodes 证据组为空" % sample.get("id"))
    return nodes


def _run_manifest(graph_path, searcher, samples_sha, source_fingerprint):
    """冻结 manifest（F04）：runner/scorer/样本摘要/图与知识代际/词表指纹/代码指纹。"""
    from .observation import collect_version
    version = collect_version(searcher, graph_path)
    return {"runner": RUNNER_VERSION, "scorer": SCORER_VERSION,
            "samples_sha256": samples_sha,
            "graph": {"mtime": version.get("graph_mtime"),
                      "size": version.get("graph_size"),
                      "nodes": version.get("nodes")},
            "knowledge": version.get("knowledge"),
            "seeds_sha256": version.get("seeds_sha256"),
            "source_fingerprint": source_fingerprint or "unknown"}


def run_replay(graph_path, searcher, samples, samples_sha, label,
               notes=None, source_fingerprint=None, cluster_id=None):
    """执行样本集并登记 ReplayRun（F02/F04 纠正版）。

    - 评分：精确节点身份——返回候选的主候选（seeds，非扩展项）中首次出现期望节点
      的位置即名次；同文件其他节点不算命中；Hit@top_k 只看主候选前 top_k。
    - 确定性核心：semantic/rerank/embed 显式设 False（不允许环境开关重新启用）。
    - manifest 冻结入 params_json；逐样本绑定记录事件 event_id 与候选 id 快照。
    """
    from .observation import run_query
    from .graph import load_seeds
    seeds = load_seeds(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "seeds.json"))
    manifest = _run_manifest(graph_path, searcher, samples_sha, source_fingerprint)
    results = []
    for s in samples:
        params = dict(s.get("params") or {})
        params.setdefault("top_k", 6)
        params.setdefault("expand", False)
        # 确定性核心：显式关闭可选层（enabled(None) 的环境回退不再适用）
        params["semantic"] = False
        params["rerank"] = False
        params["embed"] = False
        params.pop("rerank_pool", None)
        params["seeds"] = seeds
        r, obs = run_query(graph_path, searcher, s["query"], "cli", params,
                           trigger_kind="replay", keep_text=False)
        refused = bool(r.get("refused"))
        seed_nodes = r.get("seeds") or []
        rank = None
        want = _expect_nodes(s)
        if not refused and want is not None:
            rank = next((i + 1 for i, n in enumerate(seed_nodes)
                         if n.get("id") in want), None)
        top_k = int(params["top_k"])
        ok = refused if s.get("expect") == "refused" else (
            rank is not None and rank <= top_k)
        results.append({"id": s["id"], "refused": refused, "rank": rank,
                        "top_k": top_k, "ok": ok,
                        "event_id": obs.get("event_id"),
                        "candidate_ids": [n.get("id") for n in seed_nodes[:10]],
                        "expected_nodes": sorted(want) if want is not None else None})
    summary = {"total": len(results), "ok": sum(1 for x in results if x["ok"]),
               "missed": sum(1 for x in results if not x["ok"]),
               "refused_kept": sum(1 for x in results if x["refused"])}
    run_id = "rp:" + hashlib.sha256(
        (label + samples_sha + str(time.time())).encode("utf-8")).hexdigest()[:16]
    db = _connect(os.path.join(os.path.dirname(os.path.abspath(graph_path)),
                               "queries.db"))
    try:
        with db:
            db.execute(
                "INSERT INTO replay_runs VALUES (?,?,?,?,?,?,?,?,?)",
                (run_id, time.time(), label, source_fingerprint or "unknown",
                 samples_sha, _canonical(manifest), _canonical(results),
                 _canonical(summary), notes))
            if cluster_id:
                db.execute(
                    "INSERT OR IGNORE INTO replay_cluster_links VALUES (?,?)",
                    (run_id, cluster_id))
    finally:
        db.close()
    out = {"run_id": run_id, "label": label, "samples_sha256": samples_sha,
           "results": results, "summary": summary, "manifest": manifest}
    return out


def get_run(graph_path, run_id):
    db = _connect(os.path.join(os.path.dirname(os.path.abspath(graph_path)),
                               "queries.db"))
    try:
        row = db.execute(
            "SELECT run_id, created, label, source_fingerprint, samples_sha256,"
            " params_json, results_json, summary_json, notes FROM replay_runs"
            " WHERE run_id=?", (run_id,)).fetchone()
    finally:
        db.close()
    if not row:
        return None
    try:
        manifest = json.loads(row[5])
    except (ValueError, TypeError):
        manifest = None  # 旧版 run：缺 manifest，保留为历史，不参与激活
    return {"run_id": row[0], "created": row[1], "label": row[2],
            "source_fingerprint": row[3], "samples_sha256": row[4],
            "manifest": manifest, "results": json.loads(row[6]),
            "summary": json.loads(row[7]), "notes": row[8]}


def compare_runs(baseline, candidate):
    """基线/候选比较（F04 纠正）。

    - manifest 冻结维度必须一致（runner/scorer/样本摘要/图与知识代际/词表指纹）；
      代码指纹按设计允许不同（基线 vs 候选正是代码差异）。旧版无 manifest 的 run
      明确拒绝比较（保留为诊断历史）。
    - 样本集合必须完整一致：缺样本或多出样本均拒绝。
    """
    mb, mc = baseline.get("manifest"), candidate.get("manifest")
    if not mb or not mc:
        raise ValueError("任一 run 缺少冻结 manifest（旧版 run 仅作历史，不可比较）")
    for dim in FROZEN_DIMENSIONS:
        if mb.get(dim) != mc.get(dim):
            raise ValueError("冻结维度 %s 不一致，两次 run 不可比（%r vs %r）"
                             % (dim, mb.get(dim), mc.get(dim)))
    b = {x["id"]: x for x in baseline["results"]}
    c = {x["id"]: x for x in candidate["results"]}
    if set(b) != set(c):
        missing = set(b) - set(c)
        extra = set(c) - set(b)
        raise ValueError("样本集合不一致：缺 %s 多 %s"
                         % (sorted(missing), sorted(extra)))
    regressions, improvements, unchanged = [], [], 0
    for sid in b:
        if sid not in c:
            raise ValueError("候选 run 缺样本：%s" % sid)
        if b[sid]["ok"] and not c[sid]["ok"]:
            regressions.append({"id": sid, "baseline": b[sid], "candidate": c[sid]})
        elif not b[sid]["ok"] and c[sid]["ok"]:
            improvements.append({"id": sid, "baseline": b[sid], "candidate": c[sid]})
        else:
            unchanged += 1
    return {"regressions": regressions, "improvements": improvements,
            "unchanged": unchanged,
            "baseline_ok": baseline["summary"]["ok"],
            "candidate_ok": candidate["summary"]["ok"],
            "verdict": "regressed" if regressions else
                       ("improved" if improvements else "no_change")}


def _runs_equivalent(baseline, rollback):
    """回滚等价（F04）：逐样本 rank/refused/ok 一致且代码指纹与基线相同。"""
    if rollback["source_fingerprint"] != baseline["source_fingerprint"]:
        return False, "回滚 run 代码指纹与基线不同（%s vs %s）" % (
            rollback["source_fingerprint"], baseline["source_fingerprint"])
    b = {x["id"]: x for x in baseline["results"]}
    r = {x["id"]: x for x in rollback["results"]}
    if set(b) != set(r):
        return False, "回滚 run 样本集合与基线不一致"
    for sid in b:
        for key in ("ok", "rank", "refused"):
            if b[sid].get(key) != r[sid].get(key):
                return False, "样本 %s 的 %s 与基线不同" % (sid, key)
    return True, None


def record_improvement(graph_path, cluster_id, baseline_run, candidate_run,
                       decision, diagnosis_id=None, rollback_run=None, notes=None,
                       source_fingerprint=None):
    """登记改进决定（F04 纠正：activated 必须有完整可核验 lineage）。

    activated 前置条件（全部拒绝式校验）：
    1. 簇存在；diagnosis_id 必填且属于该簇。
    2. 三 run 存在且冻结 manifest 一致（compare_runs 校验）。
    3. candidate 对 baseline 判定 improved（零回归由判定定义保证）。
    4. rollback run 与 baseline 逐样本等价且代码指纹相同（真实回滚演练）。
    5. candidate 代码指纹非 unknown、manifest 齐备。
    rejected/rolled_back 决定仅要求 run 存在（记录失败历史），不作 lineage 强校验。
    """
    if decision not in ("activated", "rejected", "rolled_back"):
        raise ValueError("decision 必须是 activated/rejected/rolled_back")
    db = _loop_connect(os.path.join(os.path.dirname(os.path.abspath(graph_path)),
                                    "queries.db"))
    try:
        if not db.execute("SELECT 1 FROM issue_clusters WHERE cluster_id=?",
                          (cluster_id,)).fetchone():
            raise ValueError("问题簇不存在：%s（无 lineage 不得登记启用）" % cluster_id)
        base = get_run(graph_path, baseline_run)
        cand = get_run(graph_path, candidate_run)
        if base is None or cand is None:
            raise ValueError("基线/候选 run 不存在")
        verdict = compare_runs(base, cand)["verdict"]
        if decision == "activated":
            if not diagnosis_id or not db.execute(
                    "SELECT 1 FROM diagnoses WHERE diagnosis_id=? AND cluster_id=?",
                    (diagnosis_id, cluster_id)).fetchone():
                raise ValueError("activated 必须绑定属于该簇的现存诊断（diagnosis_id）")
            if verdict != "improved":
                raise ValueError("候选 run 对基线判定为 %s，无改进依据不得登记 "
                                 "activated" % verdict)
            if not cand.get("source_fingerprint") \
                    or cand["source_fingerprint"] == "unknown":
                raise ValueError("候选 run 缺真实代码指纹（unknown），不得登记 activated")
            if not base.get("manifest") or not cand.get("manifest"):
                raise ValueError("基线/候选 run 缺冻结 manifest（旧版 run 不可用于激活）")
        rollback = None
        if rollback_run:
            rollback = get_run(graph_path, rollback_run)
            if rollback is None:
                raise ValueError("回滚 run 不存在")
            if decision == "activated":
                equivalent, why = _runs_equivalent(base, rollback)
                if not equivalent:
                    raise ValueError("回滚演练与基线不等价：%s" % why)
        improvement_id = "imp:" + hashlib.sha256(
            (cluster_id + candidate_run + decision + str(time.time())).encode("utf-8")
        ).hexdigest()[:20]
        with db:
            db.execute("INSERT INTO improvements VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (improvement_id, cluster_id, diagnosis_id, baseline_run,
                        candidate_run, rollback_run, decision, time.time(),
                        source_fingerprint, notes))
        return {"improvement_id": improvement_id, "cluster_id": cluster_id,
                "decision": decision, "verdict": verdict}
    finally:
        db.close()


def chain(graph_path, cluster_id=None):
    """闭环追溯链：簇 → 用户事件（含原始查询与反馈修订）→ 诊断 → 回放 run → 启用决定。"""
    from .feedback import FeedbackStore
    db_path = os.path.join(os.path.dirname(os.path.abspath(graph_path)), "queries.db")
    db = _loop_connect(db_path)
    out = {"cluster": None, "events": [], "feedback": [], "diagnoses": [],
           "replay_runs": [], "improvements": []}
    try:
        if cluster_id is None:
            row = db.execute(
                "SELECT cluster_id FROM improvements ORDER BY decided_at DESC"
                " LIMIT 1").fetchone()
            if row is None:
                return out
            cluster_id = row[0]
        c = db.execute(
            "SELECT cluster_id, query_digest, event_count, status, first_seen,"
            " last_seen FROM issue_clusters WHERE cluster_id=?",
            (cluster_id,)).fetchone()
        if c:
            out["cluster"] = {"cluster_id": c[0], "query_digest": c[1],
                              "event_count": c[2], "status": c[3],
                              "first_seen": c[4], "last_seen": c[5]}
        evs = db.execute(
            "SELECT e.event_id, e.entry, e.trigger_kind, e.created, e.status,"
            " e.refusal_reason, e.query_text FROM query_events e"
            " JOIN cluster_events ce ON ce.event_id=e.event_id AND ce.cluster_id=?"
            " ORDER BY e.created", (cluster_id,)).fetchall()
        out["events"] = [{"event_id": r[0], "entry": r[1], "trigger_kind": r[2],
                          "created": r[3], "status": r[4], "refusal_reason": r[5],
                          "query_text": r[6]} for r in evs]
        fbs = db.execute(
            "SELECT f.feedback_id, f.event_id, f.revision, f.relevance, f.task_outcome,"
            " f.source, f.reason, f.created FROM feedback f JOIN cluster_events ce"
            " ON ce.event_id=f.event_id AND ce.cluster_id=? ORDER BY f.created",
            (cluster_id,)).fetchall()
        out["feedback"] = [{"feedback_id": r[0], "event_id": r[1], "revision": r[2],
                            "relevance": r[3], "task_outcome": r[4], "source": r[5],
                            "reason": r[6], "created": r[7]} for r in fbs]
        dgs = db.execute(
            "SELECT diagnosis_id, created, ai_status, pack_json FROM diagnoses"
            " WHERE cluster_id=? ORDER BY created", (cluster_id,)).fetchall()
        out["diagnoses"] = []
        for r in dgs:
            pack = json.loads(r[3])
            out["diagnoses"].append({
                "diagnosis_id": r[0], "created": r[1], "ai_status": r[2],
                "findings": [{"check": f["check"], "result": f["result"]}
                             for f in pack.get("findings", [])],
                "hypotheses": pack.get("hypotheses", []),
                "unknowns": pack.get("unknowns", [])})
        # F04 纠正：只显示与该簇关联的 run——显式 replay_cluster_links 或
        # improvements 引用的基线/候选/回滚；不再罗列工作区全部 run
        linked = {r[0] for r in db.execute(
            "SELECT run_id FROM replay_cluster_links WHERE cluster_id=?",
            (cluster_id,)).fetchall()}
        for r in db.execute(
                "SELECT baseline_run, candidate_run, rollback_run FROM improvements"
                " WHERE cluster_id=?", (cluster_id,)).fetchall():
            linked.update(x for x in r if x)
        runs = (db.execute(
            "SELECT run_id, created, label, source_fingerprint, samples_sha256,"
            " summary_json, notes FROM replay_runs WHERE run_id IN (%s)"
            " ORDER BY created" % (",".join("?" * len(linked)) or "NULL"),
            sorted(linked)).fetchall() if linked else [])
        out["replay_runs"] = [{"run_id": r[0], "created": r[1], "label": r[2],
                               "source_fingerprint": r[3],
                               "samples_sha256": r[4], "summary": json.loads(r[5]),
                               "notes": r[6]} for r in runs]
        imps = db.execute(
            "SELECT improvement_id, diagnosis_id, baseline_run, candidate_run,"
            " rollback_run, decision, decided_at, notes FROM improvements"
            " WHERE cluster_id=? ORDER BY decided_at", (cluster_id,)).fetchall()
        out["improvements"] = [
            {"improvement_id": r[0], "diagnosis_id": r[1], "baseline_run": r[2],
             "candidate_run": r[3], "rollback_run": r[4], "decision": r[5],
             "decided_at": r[6], "notes": r[7]} for r in imps]
        return out
    finally:
        db.close()
