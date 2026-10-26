"""retrieval-feedback：反馈修订、统计口径、删除恢复与导出契约（AC-R15-02）。

口径红线：有候选不算 hit；unknown 不算 miss；partial 不折算；来源分列不合并；
AI 意见不覆盖人源；重复去重；删除需先备份且恢复完整。
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import domimap.lite_scan as ls  # noqa: E402
from domimap.feedback import FeedbackError, FeedbackStore  # noqa: E402
from domimap.graph import Graph, load_seeds  # noqa: E402
from domimap.observation import Recorder  # noqa: E402
from domimap.search import Searcher  # noqa: E402
from domimap.ui import make_server  # noqa: E402

VERSION_STUB = {"domimap": "test", "graph_mtime": 1, "graph_size": 1,
                "nodes": 1, "idx_schema": "test"}


def build_workspace(prefix="dm-fb-"):
    tmp = tempfile.mkdtemp(prefix=prefix)
    ws = os.path.join(tmp, "mini")
    shutil.copytree(os.path.join(HERE, "fixtures", "mini"), ws)
    g = Graph()
    g.build_from_records(ls.scan_repo(ws, repo_label="mini"),
                         load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
    gp = os.path.join(tmp, "graph.json")
    g.save(gp)
    return tmp, gp, Searcher(g)


def record_event(graph_path, text, params=None, trigger="user", keep_text=False,
                 status="ok", refusal_reason=None, entry="cli"):
    rec = Recorder(graph_path)
    obs = rec.record_query(entry=entry, text=text, params=params or {"top_k": 6},
                           version=VERSION_STUB, status=status,
                           refusal_reason=refusal_reason, trigger_kind=trigger,
                           keep_text=keep_text, result={"candidates": []})
    assert obs["status"] == "recorded", obs
    return obs["event_id"]


class TestFeedbackSemantics(unittest.TestCase):
    def setUp(self):
        self.tmp, self.gp, _ = build_workspace()
        self.store = FeedbackStore(os.path.join(self.tmp, "queries.db"))

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_submit_hit_and_effective(self):
        ev = record_event(self.gp, "订单 改价")
        r = self.store.submit(ev, "hit", task_outcome="success", reason="前两条即目标")
        self.assertEqual(r["status"], "recorded")
        self.assertEqual(r["revision"], 1)
        eff = self.store.effective(ev)
        self.assertEqual(eff["relevance"], "hit")
        self.assertFalse(eff["disputed"])

    def test_revision_appends_and_supersedes_keeps_history(self):
        ev = record_event(self.gp, "订单 改价")
        self.store.submit(ev, "hit")
        with self.assertRaises(FeedbackError):
            self.store.submit(ev, "miss", reason="无修订号的同来源改判被拒绝")
        r2 = self.store.submit(ev, "miss", reason="看错了，第一条才是别的表",
                               expected_revision=1)
        self.assertEqual(r2["revision"], 2)
        detail = self.store.event_detail(ev)
        self.assertEqual(len(detail["feedback"]), 2, "修订追加，历史保留")
        self.assertEqual(detail["effective"]["relevance"], "miss")
        self.assertIsNotNone(detail["feedback"][0]["superseded_by"])
        self.assertIsNone(detail["feedback"][1]["superseded_by"])

    def test_unknown_events_and_enums_rejected(self):
        with self.assertRaises(FeedbackError):
            self.store.submit("qe:deadbeefdeadbeefdeadbeef", "hit")
        ev = record_event(self.gp, "订单")
        with self.assertRaises(FeedbackError):
            self.store.submit(ev, "definitely-hit")

    def test_stats_unknown_not_miss(self):
        record_event(self.gp, "订单 改价")
        record_event(self.gp, "库存 预警")
        s = self.store.stats()
        self.assertEqual(s["effective"]["miss"], 0, "未反馈不是 miss")
        self.assertEqual(s["effective"]["unknown"], 2)
        self.assertIsNone(s["hit_rate"])
        self.assertEqual(s["unfeedbacked"], 2)
        self.assertEqual(s["judgment_coverage"], 0.0)

    def test_ai_suggestion_never_overrides_user(self):
        ev = record_event(self.gp, "订单 改价")
        self.store.submit(ev, "miss", source="user_feedback")
        self.store.submit(ev, "hit", source="ai_suggestion", reason="自评分")
        eff = self.store.effective(ev)
        self.assertEqual(eff["relevance"], "miss", "AI 意见不得覆盖人源")
        s = self.store.stats()
        self.assertEqual(s["by_source"]["ai_suggestion"].get("hit", 0), 1,
                         "AI 自评分单独统计可见")
        self.assertEqual(s["effective"]["miss"], 1)

    def test_disputed_authoritative_sources(self):
        ev = record_event(self.gp, "订单 改价")
        self.store.submit(ev, "hit", source="user_feedback")
        self.store.submit(ev, "miss", source="human_annotation")
        eff = self.store.effective(ev)
        self.assertTrue(eff["disputed"])
        self.assertIsNone(eff["relevance"])
        s = self.store.stats()
        self.assertEqual(s["effective"]["disputed"], 1)
        self.assertEqual(s["effective"]["hit"] + s["effective"]["miss"], 0,
                         "争议样本不进命中率分子或分母")

    def test_correct_abstention_ratio(self):
        ev1 = record_event(self.gp, "量子玄学", status="refused",
                           refusal_reason="coverage_below_min")
        ev2 = record_event(self.gp, "紫微斗数", status="refused",
                           refusal_reason="coverage_below_min")
        self.store.submit(ev1, "not_applicable", task_outcome="correct_abstention")
        # ev2 拒答但无反馈：只进分母
        s = self.store.stats()
        self.assertEqual(s["correct_refusal"]["refused_with_feedback"], 1)
        self.assertEqual(s["correct_refusal"]["correct_abstention"], 1)
        self.assertEqual(s["correct_refusal"]["ratio"], 1.0)

    def test_hit_rate_formula_and_partial_not_full_hit(self):
        events = [record_event(self.gp, "查询%d" % i) for i in range(4)]
        self.store.submit(events[0], "hit")
        self.store.submit(events[1], "partial")
        self.store.submit(events[2], "miss")
        # events[3] 无反馈
        s = self.store.stats()
        self.assertEqual(s["hit_rate"], round(1 / 3, 4), "H/(H+P+M)，partial 单列不折算")
        self.assertEqual(s["hit_rate_denominator"], 3)
        self.assertEqual(s["effective"]["partial"], 1)

    def test_trigger_non_user_separated(self):
        ev = record_event(self.gp, "回放查询", trigger="replay")
        self.store.submit(ev, "miss", source="dev_gold")
        s = self.store.stats()
        self.assertEqual(s["trigger"]["non_user"], 1)
        self.assertEqual(s["trigger"]["user"], 0)
        self.assertEqual(s["effective"]["miss"], 0,
                         "回放/开发事件的判定不得并入用户口径")
        self.assertEqual(s["non_user_effective"]["miss"], 1, "非 user 口径单独可见")
        ev2 = record_event(self.gp, "真实查询")
        self.store.submit(ev2, "hit", source="user_feedback")
        s2 = self.store.stats()
        self.assertEqual(s2["effective"]["hit"], 1)
        self.assertEqual(s2["effective"]["miss"], 0)
        self.assertEqual(s2["non_user_effective"]["miss"], 1)

    def test_dedup_profile_and_occurrences(self):
        params = {"top_k": 6}
        for _ in range(3):
            record_event(self.gp, "同一查询", params=params)
        evs = [r[0] for r in sqlite3.connect(
            os.path.join(self.tmp, "queries.db")).execute(
            "SELECT event_id FROM query_events")]
        self.store.submit(evs[0], "miss", source="user_feedback")
        s = self.store.stats()
        self.assertEqual(s["profiles"]["distinct"], 1)
        self.assertEqual(s["profiles"]["repeated_events"], 2)
        self.assertEqual(s["hit_rate_denominator"], 1, "重复查询只算一个样本")
        samples = self.store.export_samples("failure")
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0]["occurrences"], 3)

    def test_idempotent_and_conflict_feedback(self):
        ev = record_event(self.gp, "订单 改价")
        a = self.store.submit(ev, "miss", idempotency_key="fb-key-1")
        b = self.store.submit(ev, "miss", idempotency_key="fb-key-1")
        self.assertEqual((a["status"], b["status"]), ("recorded", "duplicate"))
        c = self.store.submit(ev, "hit", idempotency_key="fb-key-1")
        self.assertEqual(c["status"], "conflict")
        detail = self.store.event_detail(ev)
        self.assertEqual(len(detail["feedback"]), 1, "冲突不落新修订")
        self.assertEqual(detail["effective"]["relevance"], "miss")

    def test_export_replayable_flag(self):
        ev_text = record_event(self.gp, "带原文的失败查询", keep_text=True)
        ev_notext = record_event(self.gp, "无原文的失败查询")
        self.store.submit(ev_text, "miss")
        self.store.submit(ev_notext, "miss")
        samples = {s["event_id"]: s for s in self.store.export_samples("failure")}
        self.assertTrue(samples[ev_text]["replayable"])
        self.assertFalse(samples[ev_notext]["replayable"], "未保存原文不得伪造可回放")
        self.assertIsNone(samples[ev_notext]["query_text"])

    def test_concurrent_revisions_contract(self):
        """F07 后契约：同来源并发改判需 expected_revision（其余拒绝）；多来源并行全落。"""
        ev = record_event(self.gp, "并发反馈")
        errs = []

        def worker(i):
            try:
                self.store.submit(ev, "hit" if i % 2 == 0 else "miss",
                                  source="user_feedback")
            except FeedbackError:
                errs.append("rev")
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        landed = self.store.db.execute(
            "SELECT COUNT(*) FROM feedback WHERE event_id=? AND source='user_feedback'",
            (ev,)).fetchone()[0]
        self.assertEqual(landed, 1, "同来源无修订号的并发改判只有第一条落库")
        # 8 个 worker 按奇偶提交两种判定：与赢家同判的 3 个为 duplicate，
        # 异判的 4 个被拒绝（4/4 对半，errs 恒为 4）
        self.assertEqual(len(errs), 4)
        # 不同来源为并行意见：全部落库且互不覆盖
        for i, sname in enumerate(("human_annotation", "dev_gold", "rule_check")):
            self.store.submit(ev, "hit" if i % 2 == 0 else "miss", source=sname)
        detail = self.store.event_detail(ev)
        self.assertEqual(len(detail["feedback"]), 4)
        self.assertIsNotNone(detail["effective"])

    def test_delete_requires_backup_and_restore_roundtrip(self):
        ev = record_event(self.gp, "待删除")
        self.store.submit(ev, "miss")
        with self.assertRaises(FeedbackError):
            self.store.delete_events(delete_all=True)  # 未出示备份
        backup = os.path.join(self.tmp, "backup-queries.db")
        self.store.snapshot(backup)
        r = self.store.delete_events(delete_all=True, backup_path=backup)
        self.assertEqual(r["deleted_events"], 1)
        self.assertEqual(r["deleted_feedback"], 1)
        self.assertEqual(self.store.stats()["events"], 0)
        self.store.restore(backup)
        detail = self.store.event_detail(ev)
        self.assertEqual(detail["effective"]["relevance"], "miss", "恢复后事件与反馈完整")
        # 损坏快照拒绝恢复且原库不动
        bad = os.path.join(self.tmp, "bad.db")
        with open(bad, "wb") as f:
            f.write(b"not a sqlite file")
        with self.assertRaises(FeedbackError):
            self.store.restore(bad)
        self.assertEqual(self.store.event_detail(ev)["effective"]["relevance"], "miss")

    def test_delete_by_ids_and_before(self):
        ev1 = record_event(self.gp, "删除1")
        time.sleep(0.01)
        t_mark = time.time()
        time.sleep(0.01)
        ev2 = record_event(self.gp, "保留")
        self.store.submit(ev1, "hit")
        r = self.store.delete_events(ids=[ev1])
        self.assertEqual((r["deleted_events"], r["deleted_feedback"]), (1, 1))
        self.assertIsNone(self.store.event_detail(ev1))
        self.assertIsNotNone(self.store.event_detail(ev2))
        r2 = self.store.delete_events(before=t_mark)
        self.assertEqual(r2["deleted_events"], 0)  # ev2 晚于 t_mark


class TestDriftC3Stats(unittest.TestCase):
    """drift-correction-c3（F07）：统计口径与反馈冲突契约。"""

    def setUp(self):
        self.tmp, self.gp, _ = build_workspace(prefix="dm-c3-")
        self.store = FeedbackStore(os.path.join(self.tmp, "queries.db"))

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ai_feedback_does_not_change_human_rate(self):
        # probes.json: ai_suggestion_changes_human_rate
        a = record_event(self.gp, "重复查询")
        b = record_event(self.gp, "重复查询")
        self.store.submit(a, "miss")
        self.store.submit(b, "hit")
        before = self.store.stats()["hit_rate"]
        self.store.submit(a, "hit", source="ai_suggestion")
        after = self.store.stats()["hit_rate"]
        self.assertEqual(before, after, "AI 建议不得改变人工样本的选用")
        self.assertEqual(after, 1.0, "以最新人工判定为准（hit）")

    def test_replay_event_does_not_pollute_user_unknown(self):
        # probes.json: replay_pollutes_user_unknown
        record_event(self.gp, "用户查询")
        before = self.store.stats()["effective"]["unknown"]
        record_event(self.gp, "仅回放无反馈", trigger="replay")
        after = self.store.stats()["effective"]["unknown"]
        self.assertEqual(before, after, "replay 事件不得改变用户 unknown/覆盖率")

    def test_reason_change_same_key_is_conflict(self):
        # probes.json: feedback_reason_conflict
        e = record_event(self.gp, "理由变更")
        a = self.store.submit(e, "miss", reason="first", idempotency_key="fb-key-c3")
        b = self.store.submit(e, "miss", reason="changed", idempotency_key="fb-key-c3")
        self.assertEqual((a["status"], b["status"]), ("recorded", "conflict"))
        stored = self.store.db.execute(
            "SELECT reason FROM feedback WHERE idempotency_key=?", ("fb-key-c3",)
        ).fetchone()[0]
        self.assertEqual(stored, "first", "冲突不得覆盖原修订")

    def test_hit_rate_by_source_reported(self):
        e1 = record_event(self.gp, "来源甲")
        e2 = record_event(self.gp, "来源乙")
        self.store.submit(e1, "hit", source="user_feedback")
        self.store.submit(e2, "miss", source="human_annotation")
        s = self.store.stats()
        self.assertEqual(s["hit_rate_by_source"]["user_feedback"]["hit"], 1)
        self.assertEqual(s["hit_rate_by_source"]["user_feedback"]["hit_rate"], 1.0)
        self.assertEqual(s["hit_rate_by_source"]["human_annotation"]["hit_rate"], 0.0)
        self.assertIn("metric_definitions", s)

    def test_expected_revision_conflict(self):
        e = record_event(self.gp, "修订冲突")
        self.store.submit(e, "hit")
        with self.assertRaises(FeedbackError):
            self.store.submit(e, "miss", expected_revision=99)
        ok = self.store.submit(e, "miss", expected_revision=1)
        self.assertEqual(ok["revision"], 2)


class TestFeedbackCLIAndUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.gp, _ = build_workspace(prefix="dm-fbui-")
        # CLI 先发两条查询（一条带原文便于导出）
        cls._cli(["query", "订单 改价", "-g", cls.gp, "--json"])
        p = cls._cli(["query", "量子玄学术语", "-g", cls.gp])
        assert p.returncode == 3
        db = sqlite3.connect(os.path.join(cls.tmp, "queries.db"))
        cls.event_hit = db.execute(
            "SELECT event_id FROM query_events WHERE status='ok'").fetchone()[0]
        cls.event_miss = db.execute(
            "SELECT event_id FROM query_events WHERE status='refused'").fetchone()[0]
        db.close()
        cls.srv = make_server(cls.gp, port=0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def _cli(cls, args):
        return subprocess.run([sys.executable, "-m", "domimap"] + args,
                              capture_output=True, text=True, cwd=ROOT, timeout=60)

    def _jreq(self, path, method="GET", body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.port, path), data=data, method=method,
            headers=headers or ({"Content-Type": "application/json"} if data else {}))
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_cli_feedback_history_stats_export(self):
        p = self._cli(["feedback", self.event_miss, "--relevance", "not_applicable",
                       "--outcome", "correct_abstention", "--reason", "资料确实没有",
                       "-g", self.gp])
        self.assertEqual(p.returncode, 0, p.stderr)
        r = json.loads(p.stdout)
        self.assertEqual(r["status"], "recorded")
        p2 = self._cli(["qstats", "-g", self.gp, "--json"])
        self.assertEqual(p2.returncode, 0)
        s = json.loads(p2.stdout)
        self.assertEqual(s["correct_refusal"]["correct_abstention"], 1)
        p3 = self._cli(["history", "-g", self.gp, "--status", "refused", "--json"])
        self.assertEqual(p3.returncode, 0)
        h = json.loads(p3.stdout)
        self.assertEqual(h["total"], 1)
        self.assertEqual(h["items"][0]["event_id"], self.event_miss)
        # 导出：把 ok 事件标 miss 后导出失败样例（无原文 → replayable=false）
        p4 = self._cli(["feedback", self.event_hit, "--relevance", "miss",
                        "-g", self.gp])
        self.assertEqual(p4.returncode, 0)
        out = os.path.join(self.tmp, "samples.json")
        p5 = self._cli(["qexport", "--kind", "failure", "-g", self.gp, "-o", out])
        self.assertEqual(p5.returncode, 0, p5.stderr)
        with open(out, encoding="utf-8") as f:
            samples = json.load(f)
        self.assertEqual(samples["count"], 1)
        self.assertFalse(samples["samples"][0]["replayable"])

    def test_cli_feedback_unknown_event(self):
        p = self._cli(["feedback", "qe:" + "0" * 24, "--relevance", "hit", "-g", self.gp])
        self.assertEqual(p.returncode, 4)

    def test_ui_feedback_stats_history_and_csrf(self):
        # 页面包含反馈入口与历史工作流（前端结构存在性；交互语义由 API 测试覆盖）
        with urllib.request.urlopen("http://127.0.0.1:%d/" % self.port, timeout=10) as r:
            html = r.read().decode("utf-8")
        for marker in ("反馈与历史", "addFeedbackBar", "没找到", "结果有误",
                       "unknown 不算 miss"):
            self.assertIn(marker, html)
        self.assertNotIn("innerHTML", html)
        code, d = self._jreq("/api/search?q=" + urllib.parse.quote("库存 同步"))
        self.assertEqual(code, 200)
        qid = d["query_id"]
        self.assertTrue(qid)
        code, r = self._jreq("/api/feedback", method="POST",
                             body={"event_id": qid, "relevance": "partial",
                                   "reason": "只找到一半"})
        self.assertEqual(code, 200)
        self.assertEqual(r["status"], "recorded")
        code, s = self._jreq("/api/feedback/stats")
        self.assertEqual(code, 200)
        self.assertEqual(s["effective"]["partial"], 1)
        code, h = self._jreq("/api/history?limit=5")
        self.assertEqual(code, 200)
        self.assertTrue(any(i["event_id"] == qid and i["feedback_relevance"] == "partial"
                            for i in h["items"]))
        # 越界枚举拒绝
        code, _ = self._jreq("/api/feedback", method="POST",
                             body={"event_id": qid, "relevance " : "hit"})
        self.assertEqual(code, 400)
        # 跨站写拒绝（R08）
        code, _ = self._jreq("/api/feedback", method="POST",
                             body={"event_id": qid, "relevance": "hit"},
                             headers={"Content-Type": "application/json",
                                      "Origin": "http://evil.example"})
        self.assertEqual(code, 403)

    def test_mcp_feedback_tool(self):
        from domimap.observation import Recorder
        from domimap.graph import Graph as _G
        from domimap.mcp import Server
        ev = Recorder(self.gp).record_query(
            entry="mcp", text="MCP 反馈查询", params={"top_k": 6},
            version={"domimap": "t"}, status="ok", result={"candidates": []}
        )["event_id"]
        srv = Server(self.gp)
        out = srv.call("kg_feedback", {"event_id": ev, "relevance": "miss",
                                       "reason": "没找到"})
        self.assertFalse(out["isError"])
        self.assertIn("recorded", out["content"][0]["text"])
        bad = srv.call("kg_feedback", {"event_id": ev, "relevance": "definitely"})
        self.assertTrue(bad["isError"], "枚举外的 relevance 必须被参数校验拒绝")

    def test_cli_lifecycle_snapshot_delete_restore(self):
        import sqlite3 as _s3
        ev = _s3.connect(os.path.join(self.tmp, "queries.db")).execute(
            "SELECT event_id FROM query_events LIMIT 1").fetchone()[0]
        backup = os.path.join(self.tmp, "snap.db")
        p = self._cli(["qsnapshot", "-g", self.gp, "-o", backup])
        self.assertEqual(p.returncode, 0, p.stderr)
        p2 = self._cli(["qdelete", "-g", self.gp, "--all", "--backup", backup])
        self.assertEqual(p2.returncode, 0, p2.stderr)
        p3 = self._cli(["qstats", "-g", self.gp, "--json"])
        self.assertEqual(json.loads(p3.stdout)["events"], 0)
        p4 = self._cli(["qrestore", "-g", self.gp, "--backup", backup])
        self.assertEqual(p4.returncode, 0, p4.stderr)
        db = _s3.connect(os.path.join(self.tmp, "queries.db"))
        back = db.execute("SELECT COUNT(*) FROM query_events WHERE event_id=?",
                          (ev,)).fetchone()[0]
        db.close()
        self.assertEqual(back, 1, "恢复后事件完整")

    def test_ui_event_detail_endpoint(self):
        import sqlite3 as _s3
        ev = _s3.connect(os.path.join(self.tmp, "queries.db")).execute(
            "SELECT event_id FROM query_events LIMIT 1").fetchone()[0]
        code, d = self._jreq("/api/event?id=" + ev)
        self.assertEqual(code, 200)
        self.assertEqual(d["event"]["event_id"], ev)
        self.assertIn("feedback", d)
        self.assertIn("effective", d)
        code, _ = self._jreq("/api/event?id=qe:" + "0" * 24)
        self.assertEqual(code, 404)
        code, _ = self._jreq("/api/event?id=not-an-id")
        self.assertEqual(code, 400)

    def test_ui_history_empty_without_db(self):
        tmp2, gp2, _ = build_workspace(prefix="dm-fbui2-")
        try:
            srv = make_server(gp2, port=0)
            port = srv.server_address[1]
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                with urllib.request.urlopen(
                        "http://127.0.0.1:%d/api/history" % port, timeout=10) as r:
                    d = json.loads(r.read())
                self.assertEqual(d["total"], 0)
                self.assertFalse(os.path.exists(os.path.join(tmp2, "queries.db")),
                                 "查看历史不得凭空建库")
            finally:
                srv.shutdown()
                srv.server_close()
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
