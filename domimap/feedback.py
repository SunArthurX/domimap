"""feedback — 查询反馈修订、历史列表、分组统计与受控删除（retrieval-feedback P2）。

命中口径（specs/tasks/retrieval-feedback.md，冻结）：
- 有返回候选绝不自动算 hit；unknown 不算 miss；partial 不折算成 hit。
- 判定来源分列统计，不合并；ai_suggestion 永不覆盖人源（user_feedback/human_annotation/dev_gold）。
- 有效相关性 = 权威来源最新修订；权威互相矛盾 → disputed（只计覆盖率不计命中率）。
- 已判定完整命中率 = H/(H+P+M)，分母不含 unknown/not_applicable/disputed。
- trigger≠user 的事件单列，不并入真实用户统计。
"""
import hashlib
import json
import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path

from .storage import synchronized

RELEVANCE_VALUES = ("unknown", "hit", "partial", "miss", "not_applicable")
TASK_OUTCOME_VALUES = ("unknown", "success", "failure", "correct_abstention",
                       "needs_clarification")
SOURCE_VALUES = ("user_feedback", "human_annotation", "dev_gold", "rule_check",
                 "ai_suggestion")
AUTHORITATIVE_SOURCES = ("user_feedback", "human_annotation", "dev_gold")

BUSY_TIMEOUT_MS = 5000

FEEDBACK_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
  feedback_id TEXT PRIMARY KEY,
  event_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  relevance TEXT NOT NULL,
  task_outcome TEXT NOT NULL,
  source TEXT NOT NULL,
  reason TEXT,
  expected_evidence TEXT,
  created REAL NOT NULL,
  idempotency_key TEXT UNIQUE,
  content_digest TEXT NOT NULL,
  superseded_by TEXT,
  UNIQUE(event_id, revision));
CREATE INDEX IF NOT EXISTS idx_feedback_event ON feedback(event_id);
"""

# 事件表结构同 observation.SCHEMA：feedback 单独开库时也要能建全（restore 校验同源）
_EVENT_SCHEMA = """
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

REASON_MAX = 200  # 导出与响应中的理由截断（本地库保留全文）


def _loop_schema_sql():
    """完整闭环 schema（events+feedback+diagnosis+replay 表）。

    diagnosis 模块 import 本模块，故 DIAG_SCHEMA/REPLAY_SCHEMA 惰性导入；
    FeedbackStore 是 queries.db 的基座，须保证恢复/删除校验能看到全部表。
    """
    from .diagnosis import DIAG_SCHEMA
    from .replay import REPLAY_SCHEMA
    return _EVENT_SCHEMA + FEEDBACK_SCHEMA + DIAG_SCHEMA + REPLAY_SCHEMA


def _canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class FeedbackError(ValueError):
    """反馈契约违反（未知事件/非法枚举/缺备份等）；调用方转 4xx，不当成功。"""


class FeedbackStore:
    """queries.db 上的反馈层：短连接、进程内锁、WAL；与事件表同库不同表。"""

    def __init__(self, db_path):
        self.db_path = db_path
        self._lock = threading.RLock()
        self.db = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_MS / 1000.0,
                                  check_same_thread=False)
        self.db.execute("PRAGMA busy_timeout=%d" % BUSY_TIMEOUT_MS)
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass
        for attempt in range(3):
            try:
                self.db.executescript(_loop_schema_sql())
                self.db.commit()
                break
            except sqlite3.OperationalError as error:
                if "locked" not in str(error) or attempt == 2:
                    raise
                time.sleep(0.02 * (attempt + 1))

    # ---------- 提交与修订 ----------
    @synchronized
    def submit(self, event_id, relevance, task_outcome="unknown", source="user_feedback",
               reason=None, expected_evidence=None, idempotency_key=None,
               expected_revision=None):
        """提交/修订反馈（F07 纠正）。

        - 幂等摘要覆盖完整规范化 payload（relevance/task_outcome/source/reason/
          expected_evidence）：同键同 payload= duplicate，同键异 payload= conflict。
        - 同来源修订判定字段必须携带 expected_revision=该来源当前最新修订号
          （乐观并发）；缺失或不符即拒绝——"独立不同意见"不再静默覆盖有效值。
          不同来源为并行意见，不互斥。
        """
        if relevance not in RELEVANCE_VALUES or task_outcome not in TASK_OUTCOME_VALUES \
                or source not in SOURCE_VALUES:
            raise FeedbackError("非法 relevance/task_outcome/source")
        if not self.db.execute("SELECT 1 FROM query_events WHERE event_id=?",
                               (event_id,)).fetchone():
            raise FeedbackError("未知查询事件：%s" % event_id)
        reason_n = ((reason or "").strip())[:4000] or None
        expected_n = (str(expected_evidence).strip())[:512] or None
        content = {"event_id": event_id, "relevance": relevance,
                   "task_outcome": task_outcome, "source": source,
                   "reason": reason_n, "expected_evidence": expected_n}
        content_digest = hashlib.sha256(_canonical(content).encode("utf-8")).hexdigest()
        # ① 幂等键先判定：同键同 payload=duplicate，同键异 payload=conflict（重投语义）
        if idempotency_key:
            feedback_id = "fb:" + hashlib.sha256(
                ("idem:" + idempotency_key).encode("utf-8")).hexdigest()[:24]
            row = self.db.execute(
                "SELECT content_digest FROM feedback WHERE idempotency_key=?",
                (idempotency_key,)).fetchone()
            if row:
                if row[0] == content_digest:
                    rev = self.db.execute(
                        "SELECT revision FROM feedback WHERE idempotency_key=?",
                        (idempotency_key,)).fetchone()[0]
                    return {"feedback_id": feedback_id, "revision": rev,
                            "status": "duplicate"}
                with self.db:
                    self.db.execute(
                        "INSERT OR IGNORE INTO idempotency_conflicts VALUES (?,?,?)",
                        (idempotency_key, content_digest, time.time()))
                return {"feedback_id": feedback_id, "status": "conflict"}
        else:
            feedback_id = "fb:" + hashlib.sha256(os.urandom(24)).hexdigest()[:24]
        # ② 同来源显式修订（F07）：判定字段变化须携带 expected_revision
        same_latest = self.db.execute(
            "SELECT feedback_id, revision, content_digest FROM feedback"
            " WHERE event_id=? AND source=? ORDER BY revision DESC LIMIT 1",
            (event_id, source)).fetchone()
        if same_latest:
            if same_latest[2] == content_digest:
                return {"feedback_id": same_latest[0], "revision": same_latest[1],
                        "status": "duplicate"}
            if expected_revision is None:
                raise FeedbackError(
                    "同来源修订需携带 expected_revision=%d（当前最新）；"
                    "独立不同意见请用不同 source" % same_latest[1])
            if int(expected_revision) != same_latest[1]:
                raise FeedbackError(
                    "expected_revision=%s 与该来源最新修订 %d 不符（并发冲突，"
                    "请重读后重试）" % (expected_revision, same_latest[1]))
        reason = reason_n
        expected_evidence = expected_n
        for attempt in range(3):
            try:
                with self.db:
                    rev_row = self.db.execute(
                        "SELECT COALESCE(MAX(revision),0) FROM feedback WHERE event_id=?",
                        (event_id,)).fetchone()
                    revision = int(rev_row[0]) + 1
                    self.db.execute(
                        "INSERT INTO feedback (feedback_id, event_id, revision, relevance,"
                        " task_outcome, source, reason, expected_evidence, created,"
                        " idempotency_key, content_digest, superseded_by)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL)",
                        (feedback_id, event_id, revision, relevance, task_outcome,
                         source, reason, expected_evidence, time.time(),
                         idempotency_key, content_digest))
                    # 仅同 source 的旧修订被指向新修订；不同 source 并存不覆盖
                    self.db.execute(
                        "UPDATE feedback SET superseded_by=? WHERE event_id=? AND source=?"
                        " AND revision<? AND superseded_by IS NULL",
                        (feedback_id, event_id, source, revision))
                break
            except sqlite3.IntegrityError as error:
                # 并发修订抢占同号：重读追加；feedback_id 撞库（幂等键竞态）按幂等语义回读
                row = self.db.execute(
                    "SELECT content_digest, revision FROM feedback WHERE idempotency_key=?",
                    (idempotency_key,)).fetchone() if idempotency_key else None
                if row and row[0] == content_digest:
                    return {"feedback_id": feedback_id, "revision": row[1],
                            "status": "duplicate"}
                if attempt == 2:
                    raise FeedbackError("反馈写入冲突：%s" % error)
                time.sleep(0.02 * (attempt + 1))
        return {"feedback_id": feedback_id, "revision": revision, "status": "recorded"}

    # ---------- 读取 ----------
    def _latest_by_source(self, event_id):
        rows = self.db.execute(
            "SELECT feedback_id, source, relevance, task_outcome, reason, expected_evidence,"
            " revision, created FROM feedback f WHERE event_id=? AND NOT EXISTS ("
            "  SELECT 1 FROM feedback n WHERE n.event_id=f.event_id AND n.source=f.source"
            "  AND n.revision>f.revision)", (event_id,)).fetchall()
        return {r[1]: {"feedback_id": r[0], "relevance": r[2], "task_outcome": r[3],
                       "reason": r[4], "expected_evidence": r[5], "revision": r[6],
                       "created": r[7]} for r in rows}

    def effective(self, event_id):
        """权威来源最新修订解析：一致→该值；矛盾→disputed（relevance=None）；缺席→unknown。"""
        latest = self._latest_by_source(event_id)
        auth = {s: latest[s] for s in AUTHORITATIVE_SOURCES if s in latest}
        out = {"relevance": "unknown", "disputed": False, "sources": latest}
        if not auth:
            return out
        values = {v["relevance"] for v in auth.values()}
        if len(values) > 1:
            out["disputed"] = True
            out["relevance"] = None
        else:
            out["relevance"] = values.pop()
        return out

    def list_events(self, entry=None, status=None, refusal_reason=None, trigger=None,
                    limit=50, offset=0):
        where, args = [], []
        if entry:
            where.append("entry=?"); args.append(entry)
        if status:
            where.append("status=?"); args.append(status)
        if refusal_reason:
            where.append("refusal_reason=?"); args.append(refusal_reason)
        if trigger:
            where.append("trigger_kind=?"); args.append(trigger)
        cond = (" WHERE " + " AND ".join(where)) if where else ""
        total = self.db.execute(
            "SELECT COUNT(*) FROM query_events" + cond, args).fetchone()[0]
        rows = self.db.execute(
            "SELECT event_id, entry, trigger_kind, created, status, refusal_reason,"
            " query_digest, query_len, query_text, params_json"
            " FROM query_events" + cond + " ORDER BY created DESC, rowid DESC LIMIT ? OFFSET ?",
            args + [int(limit), int(offset)]).fetchall()
        items = []
        for r in rows:
            eff = self.effective(r[0])
            items.append({"event_id": r[0], "entry": r[1], "trigger_kind": r[2],
                          "created": r[3], "status": r[4], "refusal_reason": r[5],
                          "query_digest": r[6][:16], "query_len": r[7],
                          "query_preview": (r[8][:60] if r[8] else None),
                          "has_text": bool(r[8]),
                          "feedback_relevance": eff["relevance"],
                          "disputed": eff["disputed"],
                          "feedback_sources": sorted(eff["sources"])})
        return {"items": items, "total": total, "limit": int(limit), "offset": int(offset)}

    def event_detail(self, event_id):
        row = self.db.execute(
            "SELECT event_id, request_id, parent_event_id, entry, trigger_kind, created,"
            " query_digest, query_len, query_text, params_json, version_json, status,"
            " refusal_reason, cov, min_cov, result_json FROM query_events WHERE event_id=?",
            (event_id,)).fetchone()
        if not row:
            return None
        fb = self.db.execute(
            "SELECT feedback_id, revision, relevance, task_outcome, source, reason,"
            " expected_evidence, created, superseded_by FROM feedback WHERE event_id=?"
            " ORDER BY revision", (event_id,)).fetchall()
        return {"event": {"event_id": row[0], "request_id": row[1],
                          "parent_event_id": row[2], "entry": row[3],
                          "trigger_kind": row[4], "created": row[5],
                          "query_digest": row[6], "query_len": row[7],
                          "query_text": row[8], "params": json.loads(row[9]),
                          "version": json.loads(row[10]), "status": row[11],
                          "refusal_reason": row[12], "cov": row[13], "min_cov": row[14],
                          "result": json.loads(row[15])},
                "feedback": [{"feedback_id": f[0], "revision": f[1], "relevance": f[2],
                              "task_outcome": f[3], "source": f[4], "reason": f[5],
                              "expected_evidence": f[6], "created": f[7],
                              "superseded_by": f[8]} for f in fb],
                "effective": self.effective(event_id)}

    # ---------- 统计 ----------
    @synchronized
    def stats(self):
        events = self.db.execute(
            "SELECT event_id, status, refusal_reason, entry, trigger_kind, query_digest,"
            " params_json FROM query_events").fetchall()
        eff_by_event = {e[0]: self.effective(e[0]) for e in events}
        out = {"events": len(events), "by_status": {}, "by_entry": {},
               "by_refusal_reason": {}, "trigger": {"user": 0, "non_user": 0},
               "effective": {"hit": 0, "partial": 0, "miss": 0, "unknown": 0,
                             "not_applicable": 0, "disputed": 0},
               "non_user_effective": {"hit": 0, "partial": 0, "miss": 0, "unknown": 0,
                                      "not_applicable": 0, "disputed": 0},
               "by_source": {}, "judged": 0, "judgment_coverage": None,
               "unfeedbacked": 0, "unfeedbacked_ratio": None,
               "hit_rate": None, "hit_rate_denominator": 0,
               "correct_refusal": {"refused_with_feedback": 0, "correct_abstention": 0,
                                   "ratio": None},
               "profiles": {"distinct": 0, "repeated_events": 0}}
        profiles = {}
        for e in events:
            key = (e[5], e[6])
            profiles.setdefault(key, []).append(e)
            out["by_status"][e[1]] = out["by_status"].get(e[1], 0) + 1
            out["by_entry"][e[3]] = out["by_entry"].get(e[3], 0) + 1
            if e[2]:
                out["by_refusal_reason"][e[2]] = out["by_refusal_reason"].get(e[2], 0) + 1
            if e[4] == "user":
                out["trigger"]["user"] += 1
            else:
                out["trigger"]["non_user"] += 1
        out["profiles"]["distinct"] = len(profiles)
        out["profiles"]["repeated_events"] = len(events) - len(profiles)

        def _latest_created(eid):
            # F07：人工样本的选用时间只看权威来源——AI 建议不得改变采哪条人工判定
            auth = [v["created"] for s, v in eff_by_event[eid]["sources"].items()
                    if s in AUTHORITATIVE_SOURCES]
            return max(auth) if auth else 0.0

        # EV13：用户口径命中率只统计含 user 触发事件的 profile（取其中 user 事件的反馈）；
        # 无 user 事件的 profile（回放/开发评测）单独列 non_user_effective，不并入。
        judged_profiles = set()
        for key, group in profiles.items():
            has_user = any(e[4] == "user" for e in group)
            pool = [e for e in group if e[4] == "user"] if has_user else group
            judged = [(e[0], eff_by_event[e[0]]) for e in pool
                      if any(s in eff_by_event[e[0]]["sources"]
                             for s in AUTHORITATIVE_SOURCES)]
            bucket = out["effective"] if has_user else out["non_user_effective"]
            if not judged:
                continue
            if has_user:
                judged_profiles.add(key)
            _, eff = max(judged, key=lambda x: _latest_created(x[0]))
            if eff["disputed"]:
                bucket["disputed"] += 1
            elif eff["relevance"] in bucket:
                bucket[eff["relevance"]] += 1
        h, p, m = (out["effective"]["hit"], out["effective"]["partial"],
                   out["effective"]["miss"])
        out["hit_rate_denominator"] = h + p + m
        if h + p + m:
            out["hit_rate"] = round(h / (h + p + m), 4)
        # 覆盖率/未反馈（F07）：只用含 user 触发事件的 profile 作分母——replay/诊断
        # 事件不得改变用户的 unknown/覆盖率
        user_profiles = {k for k, g in profiles.items() if any(e[4] == "user" for e in g)}
        judged_user = 0
        for key in user_profiles:
            group = profiles[key]
            if any(any(s in eff_by_event[e[0]]["sources"] for s in AUTHORITATIVE_SOURCES)
                   for e in group if e[4] == "user"):
                judged_user += 1
        out["judged"] = judged_user
        out["user_profiles"] = len(user_profiles)
        if user_profiles:
            out["judgment_coverage"] = round(judged_user / len(user_profiles), 4)
        out["unfeedbacked"] = len(user_profiles) - judged_user
        # effective.unknown = 未获权威判定的用户 profile 数（用户分母）
        out["effective"]["unknown"] = out["unfeedbacked"]
        out["non_user_effective"]["unknown"] = 0
        if user_profiles:
            out["unfeedbacked_ratio"] = round(out["unfeedbacked"] / len(user_profiles), 4)
        # 分来源命中率（F07）：各权威来源在自己最新修订上的 H/(H+P+M)（用户 profile）
        out["hit_rate_by_source"] = {}
        for src_name in AUTHORITATIVE_SOURCES:
            h = p_ = m = 0
            for key in user_profiles:
                group = [e for e in profiles[key] if e[4] == "user"]
                judged = [e for e in group
                          if src_name in eff_by_event[e[0]]["sources"]]
                if not judged:
                    continue
                ev = max(judged, key=lambda e: eff_by_event[e[0]]["sources"][src_name]
                         ["created"])
                rel = eff_by_event[ev[0]]["sources"][src_name]["relevance"]
                if rel == "hit":
                    h += 1
                elif rel == "partial":
                    p_ += 1
                elif rel == "miss":
                    m += 1
            out["hit_rate_by_source"][src_name] = {
                "hit": h, "partial": p_, "miss": m,
                "hit_rate": round(h / (h + p_ + m), 4) if h + p_ + m else None}
        out["metric_definitions"] = {
            "hit_rate": "H/(H+P+M)，有效相关性来自权威来源最新修订；分母不含 "
                        "unknown/not_applicable/disputed；仅用户 profile，按 "
                        "(query_digest, 实际生效参数) 去重",
            "judgment_coverage": "有权威反馈的用户 profile / 全部用户 profile",
            "correct_refusal": "refusal-precision：user 触发且被拒答、并有权威反馈的"
                               "事件中 task_outcome=correct_abstention 的占比；"
                               "基于独立应拒答集合的处理准确率需独立标注集，另行统计",
            "scope": "user 触发事件与 replay/diagnostic/retry 分离（EV13）"}
        # 分来源统计（按事件不去重，按来源各自口径）
        for src in SOURCE_VALUES:
            rows = self.db.execute(
                "SELECT relevance, COUNT(*) FROM feedback f WHERE source=? AND NOT EXISTS ("
                " SELECT 1 FROM feedback n WHERE n.event_id=f.event_id AND n.source=f.source"
                " AND n.revision>f.revision) GROUP BY relevance", (src,)).fetchall()
            counts = {r: c for r, c in rows}
            out["by_source"][src] = {"latest_count": sum(counts.values()), **counts}
        # 正确拒答：user 触发的 refused 且有权威反馈的事件中被判 correct_abstention 的占比
        denom = 0
        for e in events:
            if e[1] != "refused" or e[4] != "user":
                continue
            eff = eff_by_event[e[0]]
            auth = [s for s in AUTHORITATIVE_SOURCES if s in eff["sources"]]
            if auth:
                denom += 1
                if any(eff["sources"][s]["task_outcome"] == "correct_abstention"
                       for s in auth):
                    out["correct_refusal"]["correct_abstention"] += 1
        out["correct_refusal"]["refused_with_feedback"] = denom
        if denom:
            out["correct_refusal"]["ratio"] = round(
                out["correct_refusal"]["correct_abstention"] / denom, 4)
        return out

    # ---------- 导出 ----------
    @synchronized
    def export_samples(self, kind):
        if kind not in ("success", "failure"):
            raise FeedbackError("kind 必须是 success 或 failure")
        want = "hit" if kind == "success" else "miss"
        events = self.db.execute(
            "SELECT event_id, created, query_text, query_digest, params_json, version_json,"
            " trigger_kind, status, refusal_reason FROM query_events").fetchall()
        profiles = {}
        for e in events:
            profiles.setdefault((e[3], e[4]), []).append(e)
        samples = []
        for (digest, params), group in profiles.items():
            candidates = [e for e in group
                          if self.effective(e[0])["relevance"] == want]
            if not candidates:
                continue
            ev = max(candidates, key=lambda e: (e[1], e[0]))
            eff = self.effective(ev[0])
            reason = None
            expected = None
            for s in AUTHORITATIVE_SOURCES:
                fb = eff["sources"].get(s)
                if fb and fb["relevance"] == want:
                    reason = (fb.get("reason") or "")[:REASON_MAX] or None
                    expected = fb.get("expected_evidence")
                    break
            samples.append({
                "event_id": ev[0], "kind": kind, "relevance": want,
                "query_text": ev[2], "replayable": ev[2] is not None,
                "query_digest": digest, "params": json.loads(params),
                "version": json.loads(ev[5]), "trigger_kind": ev[6],
                "status": ev[7], "refusal_reason": ev[8],
                "reason": reason, "expected_evidence": expected,
                "occurrences": len(group)})
        samples.sort(key=lambda s: s["event_id"])
        return samples

    # ---------- 删除 / 备份 / 恢复 ----------
    @synchronized
    def delete_events(self, ids=None, before=None, delete_all=False, backup_path=None):
        """受控删除：同步清理派生对象；已固定证据（improvements 引用的簇）拒绝删除。

        delete_all（须出示备份）清空 events/feedback/簇/诊断/改进记录，保留自包含的
        replay_runs（冻结样例与结果的独立历史，返回中说明）。
        """
        if not delete_all and not ids and before is None:
            raise FeedbackError("必须给出 ids/before 之一或显式 delete_all")
        if delete_all:
            if not backup_path or not os.path.exists(backup_path):
                raise FeedbackError("全量删除必须先 snapshot 到 backup_path 并出示该路径")
            if os.path.abspath(backup_path) == os.path.abspath(self.db_path):
                raise FeedbackError("备份路径不得就是当前库文件")
        fixed_clusters = {r[0] for r in self.db.execute(
            "SELECT DISTINCT cluster_id FROM improvements")}
        with self.db:
            if delete_all:
                cur_e = self.db.execute("DELETE FROM query_events")
                cur_f = self.db.execute("DELETE FROM feedback")
                cur_d = self.db.execute("DELETE FROM diagnoses")
                cur_c = self.db.execute("DELETE FROM cluster_events")
                cur_ic = self.db.execute("DELETE FROM issue_clusters")
                cur_i = self.db.execute("DELETE FROM improvements")
                kept_runs = self.db.execute(
                    "SELECT COUNT(*) FROM replay_runs").fetchone()[0]
                return {"deleted_events": cur_e.rowcount,
                        "deleted_feedback": cur_f.rowcount,
                        "deleted_diagnoses": cur_d.rowcount,
                        "deleted_clusters": cur_ic.rowcount,
                        "deleted_improvements": cur_i.rowcount,
                        "kept_replay_runs": kept_runs,
                        "backup_path": backup_path,
                        "note": "replay_runs 为自包含冻结记录予以保留；外部副本不在本工具能力内"}
            if ids is not None:
                marks = ",".join("?" * len(ids))
                target_sql = ("SELECT event_id FROM query_events WHERE event_id IN (%s)"
                              % marks)
                args = list(ids)
            else:
                target_sql = "SELECT event_id FROM query_events WHERE created<?"
                args = [before]
            protected = [r[0] for r in self.db.execute(
                "SELECT DISTINCT ce.cluster_id FROM cluster_events ce WHERE ce.event_id"
                " IN (%s) AND ce.cluster_id IN (%s)" %
                (target_sql, ",".join("?" * len(fixed_clusters)) or "NULL"),
                args + list(fixed_clusters))] if fixed_clusters else []
            if protected:
                raise FeedbackError(
                    "事件属于已登记改进记录的簇（%s），固定证据链不得删除；"
                    "如确需删除请先按纠正流程处置对应改进记录" % ", ".join(protected))
            cur_d = self.db.execute(
                "DELETE FROM diagnoses WHERE event_id IN (%s)" % target_sql, args)
            cur_f = self.db.execute(
                "DELETE FROM feedback WHERE event_id IN (%s)" % target_sql, args)
            cur_c = self.db.execute(
                "DELETE FROM cluster_events WHERE event_id IN (%s)" % target_sql, args)
            cur_e = self.db.execute(
                "DELETE FROM query_events WHERE event_id IN (%s)" % target_sql, args)
            # 空簇清理：无成员的簇连同其诊断一并移除（其反馈事件已删）
            cur_ic = self.db.execute(
                "DELETE FROM issue_clusters WHERE NOT EXISTS ("
                " SELECT 1 FROM cluster_events ce WHERE ce.cluster_id="
                " issue_clusters.cluster_id)")
            self.db.execute(
                "DELETE FROM diagnoses WHERE cluster_id NOT IN ("
                " SELECT cluster_id FROM issue_clusters)")
        return {"deleted_events": cur_e.rowcount, "deleted_feedback": cur_f.rowcount,
                "deleted_diagnoses": cur_d.rowcount, "deleted_clusters": cur_ic.rowcount,
                "kept_replay_runs": None,
                "backup_path": None}

    def snapshot(self, path):
        """一致性快照（SQLite backup API）；外部副本的后续删除不在本工具能力内。"""
        dst = sqlite3.connect(path, timeout=BUSY_TIMEOUT_MS / 1000.0)
        try:
            with self._lock:
                self.db.backup(dst)
        finally:
            dst.close()
        return {"path": path, "size": os.path.getsize(path)}

    # ---------- 安全恢复（F01：先完整校验，失败绝不触碰原库） ----------
    RESTORE_SIZE_LIMIT = 2 << 30  # 2GiB 资源上限

    @staticmethod
    def _reference_tables():
        """以内存库构建期望 schema（含 diagnosis/replay 模块的表，惰性导入防环）。"""
        from .diagnosis import DIAG_SCHEMA
        from .replay import REPLAY_SCHEMA
        ref = sqlite3.connect(":memory:")
        try:
            ref.executescript(_loop_schema_sql())
            tables = {r[0] for r in ref.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            columns = {t: [c[1] for c in ref.execute(
                "PRAGMA table_info(%s)" % t)] for t in tables}
            return tables, columns
        finally:
            ref.close()

    def _validate_backup(self, path):
        """独立只读连接上做完整校验；任何失败抛 FeedbackError，原库不受影响。"""
        if not os.path.exists(path):
            raise FeedbackError("备份不存在：%s" % path)
        if os.path.getsize(path) > FeedbackStore.RESTORE_SIZE_LIMIT:
            raise FeedbackError("备份超过恢复大小上限，拒绝")
        uri = "file:%s?mode=ro" % Path(path).resolve().as_posix().replace("?", "%3f")
        check = sqlite3.connect(uri, uri=True)
        try:
            row = check.execute("PRAGMA integrity_check").fetchone()
            if not row or row[0] != "ok":
                raise FeedbackError("备份完整性校验失败：%s" % (row[0] if row else "无结果"))
            tables = {r[0] for r in check.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            want_tables, want_columns = FeedbackStore._reference_tables()
            unknown = tables - want_tables - {"sqlite_sequence"}
            missing = want_tables - tables
            if unknown or missing:
                raise FeedbackError("备份 schema 不符：未知表 %s / 缺表 %s"
                                    % (sorted(unknown), sorted(missing)))
            for table, columns in want_columns.items():
                got = [c[1] for c in check.execute("PRAGMA table_info(%s)" % table)]
                if got != columns:
                    raise FeedbackError("备份表 %s 列结构不符：期望 %s 实得 %s"
                                        % (table, columns, got))
            for child, child_col, parent, parent_col in (
                    ("cluster_events", "event_id", "query_events", "event_id"),
                    ("feedback", "event_id", "query_events", "event_id"),
                    ("diagnoses", "event_id", "query_events", "event_id"),
                    ("cluster_events", "cluster_id", "issue_clusters", "cluster_id"),
                    ("diagnoses", "cluster_id", "issue_clusters", "cluster_id"),
                    ("improvements", "candidate_run", "replay_runs", "run_id"),
                    ("improvements", "baseline_run", "replay_runs", "run_id"),
                    ("improvements", "rollback_run", "replay_runs", "run_id"),
                    ("improvements", "cluster_id", "issue_clusters", "cluster_id")):
                orphan = check.execute(
                    "SELECT COUNT(*) FROM %s c WHERE c.%s IS NOT NULL AND NOT EXISTS ("
                    " SELECT 1 FROM %s p WHERE p.%s = c.%s)"
                    % (child, child_col, parent, parent_col, child_col)).fetchone()[0]
                if orphan:
                    raise FeedbackError("备份存在断链引用：%s.%s → %s.%s（%d 条）"
                                        % (child, child_col, parent, parent_col,
                                           orphan))
        except sqlite3.DatabaseError as error:
            raise FeedbackError("备份不可读：%s" % error)
        finally:
            check.close()

    @synchronized
    def restore(self, path):
        """安全恢复：只读校验备份 → 独占目标 → 安全副本 → staging 原子替换。

        校验或加锁失败时原库完全不受影响；被其他连接占用时明确拒绝在线原地恢复。
        """
        self._validate_backup(path)
        if os.path.islink(self.db_path):
            raise FeedbackError("目标库是符号链接，拒绝恢复")
        if not os.path.exists(self.db_path):
            shutil.copyfile(path, self.db_path)
            self._reopen()
            return {"restored_from": path, "safety_copy": None,
                    "note": "目标库此前不存在，直接落位"}
        # 独占目标库：短超时单次尝试，被占用即拒绝（不等待、不破坏）
        old_timeout = self.db.execute("PRAGMA busy_timeout").fetchone()[0]
        try:
            self.db.execute("PRAGMA busy_timeout=250")
            self.db.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as error:
            self.db.execute("PRAGMA busy_timeout=%d" % old_timeout)
            raise FeedbackError("目标库被其他连接占用，拒绝在线原地恢复：%s" % error)
        safety = "%s.pre-restore-%d" % (self.db_path, int(time.time() * 1000))
        tmp = "%s.restore-tmp-%d-%d" % (self.db_path, os.getpid(),
                                        int(time.time() * 1000))
        try:
            # 独占持有下做一致性安全副本：先 checkpoint 把 WAL 并入主库再按字节复制
            # （Connection.backup 在源连接持事务时会死锁，不用）
            try:
                self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.OperationalError:
                try:
                    self.db.execute("PRAGMA wal_checkpoint(PASSIVE)")
                except sqlite3.OperationalError:
                    pass
            with open(self.db_path, "rb") as src_f, open(safety, "wb") as out:
                while True:
                    block = src_f.read(1 << 20)
                    if not block:
                        break
                    out.write(block)
                out.flush()
                os.fsync(out.fileno())
            with open(path, "rb") as src, open(tmp, "wb") as out:
                while True:
                    block = src.read(1 << 20)
                    if not block:
                        break
                    out.write(block)
                out.flush()
                os.fsync(out.fileno())
            self.db.commit()  # 释放 EXCLUSIVE（未做任何写）
            self.db.close()
            for suffix in ("-wal", "-shm"):
                stale = self.db_path + suffix
                if os.path.exists(stale):
                    os.unlink(stale)  # 独占后本连接是唯一写者；读者需重开（见 note）
            os.replace(tmp, self.db_path)
            fd = os.open(os.path.dirname(os.path.abspath(self.db_path)), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError as error:
            for junk in (tmp,):
                if os.path.exists(junk):
                    os.unlink(junk)
            self._reopen()
            raise FeedbackError("恢复失败，原库未替换：%s" % error)
        self._reopen()
        try:
            self._validate_backup(self.db_path)  # 发布后复验
        except FeedbackError:
            shutil.copyfile(safety, self.db_path)
            self._reopen()
            raise FeedbackError("恢复后复验失败，已从安全副本回退原库")
        return {"restored_from": path, "safety_copy": safety,
                "note": "恢复期间其他进程的打开句柄需重开；外部副本不在本工具能力内"}

    def _reopen(self):
        try:
            if getattr(self, "db", None) and self.db.in_transaction:
                self.db.rollback()
        except sqlite3.Error:
            pass
        try:
            self.db.close()
        except sqlite3.Error:
            pass
        self.db = sqlite3.connect(self.db_path, timeout=BUSY_TIMEOUT_MS / 1000.0,
                                  check_same_thread=False)
        self.db.execute("PRAGMA busy_timeout=%d" % BUSY_TIMEOUT_MS)
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass
        for attempt in range(3):
            try:
                self.db.executescript(_loop_schema_sql())
                self.db.commit()
                break
            except sqlite3.OperationalError as error:
                if "locked" not in str(error) or attempt == 2:
                    raise
                time.sleep(0.02 * (attempt + 1))

    @synchronized
    def close(self):
        self.db.close()


def store_for(graph_path):
    """工作区图旁 queries.db 的反馈库（与查询记录同库）。"""
    return FeedbackStore(os.path.join(os.path.dirname(os.path.abspath(graph_path)),
                                      "queries.db"))
