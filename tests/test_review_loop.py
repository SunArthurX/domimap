"""R06 原义 + F4-02：依据变化 → 定位到陈述 → 待复核队列；检索面陈旧标记；确认绑定；点击/重建不刷新。

此前（漂移审计 §2.2/§3）：record_baseline/scan_dependencies/confirm_review 零生产调用；attach_if_present 从不传
current_digests；amend 清空 claims 但不清 claim_bindings（idx 错位可压制复核）。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from domimap import batch
from domimap.graph import build as graph_build
from domimap.knowledge import KnowledgeStore
from domimap.service import AppService
from domimap.store import EvidenceStore, EvidenceResolver

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MINI = os.path.join(HERE, "fixtures", "mini")


class TestReviewLoop(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dm-r06-")
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.repo = os.path.join(self.tmp, "mini")
        shutil.copytree(MINI, self.repo)
        self.ws = os.path.join(self.tmp, "ws")
        self.g, _ = graph_build(self.repo, self.ws)
        self.gp = os.path.join(self.ws, "graph.json")
        self.kb_path = os.path.join(self.ws, "knowledge.db")
        os.environ.pop("DOMIMAP_OBSERVE", None)

    def _ev_of(self, rel_suffix):
        store = EvidenceStore(os.path.join(self.ws, "store.db"))
        try:
            doc = next(n for n in self.g.nodes.values() if n["kind"] == "Doc" and n["file"].endswith(rel_suffix))
            return EvidenceResolver(store).for_node(doc)
        finally:
            store.close()

    def _note(self, ev_a, ev_b):
        kb = KnowledgeStore(self.kb_path)
        try:
            return kb.submit("改价与上线结论", claims=[
                {"type": "decision", "statement": "改价必须带版本号", "evidence": [ev_a], "scope": "order"},
                {"type": "observation", "statement": "上线前要过 checklist", "evidence": [ev_b], "scope": "release"},
            ], idempotency_key="k-r06")
        finally:
            kb.close()

    def _touch_source(self, rel, text):
        with open(os.path.join(self.repo, rel), "a", encoding="utf-8") as f:
            f.write(text)

    def _queue(self):
        kb = KnowledgeStore(self.kb_path)
        try:
            return kb.review_queue()
        finally:
            kb.close()

    def test_only_affected_claim_is_queued_once(self):
        ev_prd, ev_chk = self._ev_of("改价需求PRD.md"), self._ev_of("上线checklist.md")
        note = self._note(ev_prd, ev_chk)
        self.assertEqual(self._queue(), [], "无变化不产生待复核")
        self._touch_source("docs/改价需求PRD.md", "\n\n补充：改价需二次确认。\n")
        g2, _, _ = batch.update(self.ws)
        self.assertIsNotNone(g2)
        q = self._queue()
        self.assertEqual(len(q), 1, "一篇笔记两条陈述仅一条依据变化 → 恰一条待复核：%s" % q)
        self.assertEqual((q[0]["note_id"], q[0]["claim_idx"]), (note["note_id"], 0))
        self.assertEqual(q[0]["evidence"], ev_prd)
        self.assertNotEqual(q[0]["old_sha"], q[0]["new_sha"])
        self.assertTrue(q[0].get("new_evidence", "").startswith("ev:"), "提供可绑定的新证据 ID")
        batch.update(self.ws)  # 重复更新（no-op）不重复入队
        self._touch_source("docs/上线checklist.md", "")  # 空追加：内容不变
        batch.build_many([os.path.abspath(self.repo)], self.ws, force=True,
                         service_prefixes={os.path.abspath(self.repo): None})
        self.assertEqual(len(self._queue()), 1, "重复扫描不重复待办")

    def test_search_marks_stale_and_confirm_clears_it(self):
        ev_prd, ev_chk = self._ev_of("改价需求PRD.md"), self._ev_of("上线checklist.md")
        note = self._note(ev_prd, ev_chk)
        self._touch_source("docs/改价需求PRD.md", "\n\n补充：改价需二次确认。\n")
        batch.update(self.ws)
        svc = AppService(self.gp)
        r, _ = svc.query("改价 上线 结论", "cli", top_k=10)
        kn = [n for n in r["seeds"] if n["kind"] == "Knowledge"]
        self.assertTrue(kn, "知识笔记应可检索：%s" % [n["name"] for n in r["seeds"]])
        claims = kn[0]["meta"]["claims"]
        self.assertTrue(claims[0].get("stale"), "依据已变的陈述在检索面标 stale")
        self.assertFalse(claims[1].get("stale"), "未变的陈述不标")
        self.assertIn("stale", r["text"], "文本输出可见陈旧标记")
        # 点击/重建不是真实性证明：touch_note + 再次构建后仍 stale
        kb = KnowledgeStore(self.kb_path); kb.touch_note(note["note_id"]); kb.close()
        batch.build_many([os.path.abspath(self.repo)], self.ws, force=True,
                         service_prefixes={os.path.abspath(self.repo): None})
        r2, _ = AppService(self.gp).query("改价 上线 结论", "cli", top_k=10)
        self.assertTrue(next(n for n in r2["seeds"] if n["kind"] == "Knowledge")["meta"]["claims"][0].get("stale"))
        # 显式确认 = 绑定新证据
        svc = AppService(self.gp)
        done = svc.confirm_review(note["note_id"], 0)
        self.assertTrue(done["new_evidence"].startswith("ev:"))
        self.assertEqual(self._queue(), [])
        r3, _ = AppService(self.gp).query("改价 上线 结论", "cli", top_k=10)
        kn3 = next(n for n in r3["seeds"] if n["kind"] == "Knowledge")
        self.assertFalse(kn3["meta"]["claims"][0].get("stale"), "确认后不再陈旧")
        self.assertIn(done["new_evidence"], kn3["meta"]["claims"][0]["evidence"], "陈述引用更新为新版本证据")

    def test_note_created_after_last_build_is_still_tracked(self):
        ev_prd, ev_chk = self._ev_of("改价需求PRD.md"), self._ev_of("上线checklist.md")
        # 构建 → 写笔记 → 改源 → 更新：引用版本即基线，不依赖"笔记前有过一次扫描"
        self._note(ev_prd, ev_chk)
        self._touch_source("docs/上线checklist.md", "\n- 新增检查项\n")
        batch.update(self.ws)
        q = self._queue()
        self.assertEqual([(x["claim_idx"], x["evidence"]) for x in q], [(1, ev_chk)])

    def test_amend_clears_bindings_and_pending_for_note(self):
        ev_prd, ev_chk = self._ev_of("改价需求PRD.md"), self._ev_of("上线checklist.md")
        note = self._note(ev_prd, ev_chk)
        self._touch_source("docs/改价需求PRD.md", "\n\n补充。\n")
        batch.update(self.ws)
        AppService(self.gp).confirm_review(note["note_id"], 0)
        kb = KnowledgeStore(self.kb_path)
        try:
            self.assertEqual(kb.db.execute("SELECT COUNT(*) FROM claim_bindings WHERE note_id=?", (note["note_id"],)).fetchone()[0], 1)
            kb.amend(note["note_id"], "改价与上线结论（重写）", expected_revision=1,
                     claims=[{"type": "observation", "statement": "顺序变了", "evidence": [ev_chk], "scope": "x"}])
            self.assertEqual(kb.db.execute("SELECT COUNT(*) FROM claim_bindings WHERE note_id=?", (note["note_id"],)).fetchone()[0], 0,
                             "amend 重排 claims 后旧绑定必须清除（idx 错位不得压制复核）")
            self.assertEqual(kb.db.execute("SELECT COUNT(*) FROM review_pending WHERE note_id=?", (note["note_id"],)).fetchone()[0], 0)
        finally:
            kb.close()

    def test_cli_recheck_list_and_confirm(self):
        ev_prd, ev_chk = self._ev_of("改价需求PRD.md"), self._ev_of("上线checklist.md")
        note = self._note(ev_prd, ev_chk)
        self._touch_source("docs/改价需求PRD.md", "\n\n补充。\n")
        batch.update(self.ws)
        run = lambda *a: subprocess.run([sys.executable, "-B", "-m", "domimap", *a], cwd=ROOT,
                                        capture_output=True, text=True)
        p = run("recheck", "list", "-g", self.gp)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(note["note_id"], p.stdout)
        self.assertIn("改价必须带版本号", p.stdout)
        p = run("recheck", "confirm", note["note_id"], "0", "-g", self.gp)
        self.assertEqual(p.returncode, 0, p.stderr)
        p = run("recheck", "list", "-g", self.gp)
        self.assertIn("无待复核", p.stdout)
        p = run("recheck", "confirm", note["note_id"], "7", "-g", self.gp)
        self.assertNotEqual(p.returncode, 0, "不存在的待复核项不得静默成功")


if __name__ == "__main__":
    unittest.main()
