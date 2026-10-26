"""drift-correction-c1：数据生命周期契约（F01 恢复 / F08 删除与裁剪残留）。

全部来自 out/drift-audit-2026-10-26/probes.json 的可复现反例：
- 恢复必须先在备份上完成 schema/完整性/关联校验，任何失败都不得触碰原库；
  活动连接占用时明确拒绝在线原地恢复；成功恢复留安全副本。
- 删除/容量裁剪必须同步清理派生对象（诊断包中的查询原文、簇关联、孤儿簇），
  不得毁坏已被改进记录固定的证据。
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from domimap import diagnosis, observation  # noqa: E402
from domimap.feedback import FeedbackError, FeedbackStore  # noqa: E402
from domimap.graph import Graph  # noqa: E402
from domimap.observation import Recorder  # noqa: E402
from domimap.search import Searcher  # noqa: E402

VERSION_STUB = {"domimap": "t", "graph_mtime": 1, "graph_size": 1, "nodes": 1,
                "idx_schema": "t"}


def workspace(prefix="dm-c1-"):
    tmp = tempfile.mkdtemp(prefix=prefix)
    gp = os.path.join(tmp, "graph.json")
    Graph().save(gp)
    return tmp, gp, Searcher(Graph())


def record_event(gp, text, **kw):
    return Recorder(gp).record_query(
        entry="cli", text=text, params=kw.get("params", {"top_k": 6}),
        version=VERSION_STUB, status=kw.get("status", "ok"),
        refusal_reason=kw.get("refusal_reason"), trigger_kind=kw.get("trigger", "user"),
        keep_text=True, result={"candidates": []})["event_id"]


def seeded_store(tmp, gp):
    """事件+反馈+簇+诊断齐备的工作区（诊断包内含查询原文）。"""
    ev = record_event(gp, "审计保留的原始查询文本")
    fs = FeedbackStore(os.path.join(tmp, "queries.db"))
    fs.submit(ev, "miss", expected_evidence="nothing-matches-this")
    diagnosis.build_clusters(gp)
    r = diagnosis.diagnose(gp, Searcher(Graph.load(gp)), event_id=ev)
    assert r["status"] == "created", r
    return fs, ev, r["diagnosis_id"]


class TestRestoreSafety(unittest.TestCase):
    def setUp(self):
        self.tmp, self.gp, _ = workspace()
        self.ev = record_event(self.gp, "preserve me")
        self.fs = FeedbackStore(os.path.join(self.tmp, "queries.db"))
        self.fs.submit(self.ev, "hit")
        self.good = os.path.join(self.tmp, "good-backup.db")
        self.fs.snapshot(self.good)

    def tearDown(self):
        self.fs.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _columns(self):
        return [r[1] for r in self.fs.db.execute(
            "PRAGMA table_info(query_events)")]

    def _original_intact(self):
        row = self.fs.db.execute(
            "SELECT COUNT(*) FROM query_events WHERE event_id=?", (self.ev,)).fetchone()
        return row[0] == 1

    def test_bad_schema_backup_rejected_and_original_preserved(self):
        # probes.json: restore_replaces_before_schema_validation
        bad = os.path.join(self.tmp, "bad-schema.db")
        db = sqlite3.connect(bad)
        db.executescript("CREATE TABLE query_events(dummy TEXT);"
                         " CREATE TABLE feedback(dummy TEXT);")
        db.close()
        with self.assertRaises(FeedbackError):
            self.fs.restore(bad)
        self.assertIn("event_id", self._columns(), "原库结构必须保留")
        self.assertTrue(self._original_intact(), "原库数据必须保留")

    def test_unknown_extra_table_rejected(self):
        bad = os.path.join(self.tmp, "extra-table.db")
        shutil.copyfile(self.good, bad)
        db = sqlite3.connect(bad)
        db.executescript("CREATE TABLE evil_trigger(t TEXT);")
        db.commit()
        db.close()
        with self.assertRaises(FeedbackError):
            self.fs.restore(bad)
        self.assertTrue(self._original_intact())

    def test_dangling_references_rejected(self):
        bad = os.path.join(self.tmp, "dangling.db")
        shutil.copyfile(self.good, bad)
        db = sqlite3.connect(bad)
        db.execute("INSERT INTO cluster_events VALUES ('ic:dead','qe:deadbeef')")
        db.commit()
        db.close()
        with self.assertRaises(FeedbackError):
            self.fs.restore(bad)
        self.assertTrue(self._original_intact())

    def test_corrupt_file_rejected(self):
        bad = os.path.join(self.tmp, "corrupt.db")
        with open(bad, "wb") as f:
            f.write(b"definitely not sqlite" * 100)
        with self.assertRaises(FeedbackError):
            self.fs.restore(bad)
        self.assertTrue(self._original_intact())

    def test_refuses_while_other_connection_holds_lock(self):
        other = FeedbackStore(self.fs.db_path)
        try:
            other.db.execute("BEGIN EXCLUSIVE")
            with self.assertRaises(FeedbackError) as cm:
                self.fs.restore(self.good)
            self.assertIn("占用", str(cm.exception))
            self.assertTrue(self._original_intact())
        finally:
            other.db.rollback()
            other.close()

    def test_symlink_target_refused(self):
        real = os.path.join(self.tmp, "real-target.db")
        shutil.copyfile(self.fs.db_path, real)
        self.fs.close()
        linked = os.path.join(self.tmp, "linked.db")
        os.symlink(real, linked)
        try:
            fs2 = FeedbackStore(linked)
            try:
                with self.assertRaises(FeedbackError):
                    fs2.restore(self.good)
            finally:
                fs2.close()
            self.assertEqual(os.path.realpath(linked), os.path.realpath(real),
                             "符号链接目标不得被替换")
        finally:
            os.unlink(linked)
            self.fs = FeedbackStore(os.path.join(self.tmp, "queries.db"))

    def test_success_roundtrip_and_safety_copy(self):
        self.fs.delete_events(ids=[self.ev])
        self.assertEqual(self.fs.stats()["events"], 0)
        r = self.fs.restore(self.good)
        self.assertEqual(self.fs.event_detail(self.ev)["effective"]["relevance"],
                         "hit", "恢复后事件与反馈完整")
        self.assertIn("safety_copy", r)
        self.assertTrue(os.path.exists(r["safety_copy"]), "恢复前必须留安全副本")


class TestDeleteDerivedCleanup(unittest.TestCase):
    def setUp(self):
        self.tmp, self.gp, _ = workspace()
        self.fs, self.ev, self.dg_id = seeded_store(self.tmp, self.gp)

    def tearDown(self):
        self.fs.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_delete_removes_diagnosis_text_and_cluster_links(self):
        # probes.json: delete_retains_diagnosis
        self.fs.delete_events(ids=[self.ev])
        remaining = self.fs.db.execute(
            "SELECT pack_json FROM diagnoses WHERE event_id=?", (self.ev,)).fetchone()
        self.assertIsNone(remaining, "删除后不得残留含原文的诊断包")
        orphan_links = self.fs.db.execute(
            "SELECT COUNT(*) FROM cluster_events WHERE event_id=?", (self.ev,)).fetchone()
        self.assertEqual(orphan_links[0], 0)
        orphan_fb = self.fs.db.execute(
            "SELECT COUNT(*) FROM feedback WHERE event_id=?", (self.ev,)).fetchone()
        self.assertEqual(orphan_fb[0], 0)
        # 空簇清理
        empty = self.fs.db.execute(
            "SELECT COUNT(*) FROM issue_clusters c WHERE NOT EXISTS ("
            " SELECT 1 FROM cluster_events ce WHERE ce.cluster_id=c.cluster_id)"
        ).fetchone()[0]
        self.assertEqual(empty, 0)

    def test_delete_refuses_improvement_fixed_evidence(self):
        cluster = self.fs.db.execute(
            "SELECT cluster_id FROM cluster_events WHERE event_id=?",
            (self.ev,)).fetchone()[0]
        db = sqlite3.connect(self.fs.db_path)
        with db:
            db.execute(  # 直接登记一条已固定改进记录（模拟历史启用决定）
                "INSERT INTO improvements VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("imp:fixed-test", cluster, self.dg_id, "rp:base", "rp:cand",
                 None, "activated", time.time(), "fp", None))
        db.close()
        with self.assertRaises(FeedbackError) as cm:
            self.fs.delete_events(ids=[self.ev])
        self.assertIn(cluster, str(cm.exception), "固定证据链的簇必须点名拒绝")
        self.assertIsNotNone(self.fs.event_detail(self.ev))

    def test_delete_all_wipes_loop_tables_keeps_runs(self):
        from domimap import replay
        replay._connect(self.fs.db_path).close()
        backup = os.path.join(self.tmp, "pre-del.db")
        self.fs.snapshot(backup)
        r = self.fs.delete_events(delete_all=True, backup_path=backup)
        for table in ("query_events", "feedback", "cluster_events",
                      "issue_clusters", "diagnoses", "improvements"):
            n = self.fs.db.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
            self.assertEqual(n, 0, table)
        self.assertGreaterEqual(r.get("kept_replay_runs"), 0)


class TestCapacityPruneProtectsEvidence(unittest.TestCase):
    def test_prune_keeps_judged_events_and_cleans_own_derived(self):
        tmp, gp, _ = workspace()
        fs, ev, _dg = seeded_store(tmp, gp)
        try:
            old = observation.MAX_EVENTS
            observation.MAX_EVENTS = 1
            try:
                for i in range(3):
                    Recorder(gp).record_query(
                        entry="cli", text="未判定观察 %d" % i, params={"top_k": 6},
                        version=VERSION_STUB, status="ok", trigger_kind="user",
                        keep_text=True, result={"candidates": []})
            finally:
                observation.MAX_EVENTS = old
            total = fs.db.execute("SELECT COUNT(*) FROM query_events").fetchone()[0]
            self.assertLessEqual(total, observation.MAX_EVENTS + 1,
                                 "有判定反馈的事件豁免裁剪，其余按上限裁")
            self.assertEqual(
                fs.db.execute("SELECT COUNT(*) FROM query_events WHERE event_id=?",
                              (ev,)).fetchone()[0], 1, "已判定事件不得被裁剪")
            orphan_fb = fs.db.execute(
                "SELECT COUNT(*) FROM feedback f WHERE NOT EXISTS ("
                " SELECT 1 FROM query_events e WHERE e.event_id=f.event_id)"
            ).fetchone()[0]
            self.assertEqual(orphan_fb, 0, "不得产生孤儿反馈")
        finally:
            fs.close()
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
