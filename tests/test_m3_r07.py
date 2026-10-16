"""M3.4：备份恢复 / MD 互操作 / 复核版本约束（AC-R07-01/02、AC-F4-02）。"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from domimap.knowledge import ConflictError, KnowledgeStore  # noqa: E402

CL = [{"type": "decision", "statement": "改价需乐观锁", "evidence": ["ev:aaa"], "scope": "订单域"}]

def rich_kb(path):
    kb = KnowledgeStore(path)
    r = kb.submit(body="v1 正文", claims=CL, idempotency_key="e1")
    kb.amend(r["note_id"], body="v2 正文", expected_revision=1)
    kb.confirm_review(r["note_id"], 0, new_evidence=["ev:aaa"], new_sha="sha-a1")
    return kb, r["note_id"]

class TestBackupRestore(unittest.TestCase):
    def test_clean_dir_restore_full_fidelity(self):
        with tempfile.TemporaryDirectory() as tmp:
            kb, nid = rich_kb(os.path.join(tmp, "kb.db"))
            bdir = os.path.join(tmp, "backup")
            m = kb.backup(bdir)
            kb2_dir = tempfile.mkdtemp(prefix="dm-restore-")
            kb2 = KnowledgeStore.restore(bdir, os.path.join(kb2_dir, "kb.db"))
            self.assertEqual(kb2.count(), m["notes"])
            self.assertEqual(len(kb2.history(nid)), m["revisions"])
            self.assertEqual(kb2.get(nid)["claims"][0]["state"], "confirmed")
            self.assertEqual(kb2.get(nid)["body"], "v2 正文")
            self.assertTrue(kb2.list_active())

class TestMarkdownInterop(unittest.TestCase):
    def test_export_import_amend_and_stale_base_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            kb, nid = rich_kb(os.path.join(tmp, "kb.db"))
            md_dir = os.path.join(tmp, "md")
            files = kb.export_markdown(md_dir)
            self.assertTrue(files and files[0].endswith(".md"))
            body = open(files[0], encoding="utf-8").read()
            self.assertIn("base_revision: 2", body)
            # 外部修改（基于当前 base）→ 显式导入 → amend
            open(files[0], "w", encoding="utf-8").write(
                body.replace("v2 正文", "v3 外部修改"))
            r3 = kb.import_markdown(files[0])
            self.assertEqual(r3["revision"], 3)
            # 旧 base 再导入 → 冲突（防覆盖）
            open(files[0], "w", encoding="utf-8").write(body)
            with self.assertRaises(ConflictError):
                kb.import_markdown(files[0])

    def test_export_dir_not_backfilled_as_knowledge(self):
        with tempfile.TemporaryDirectory() as tmp:
            kb, _ = rich_kb(os.path.join(tmp, "kb.db"))
            md_dir = os.path.join(tmp, "md")
            kb.export_markdown(md_dir)
            before = kb.count()
            import domimap.lite_scan as ls
            ls.scan_repo(md_dir, repo_label="x")  # 扫描导出目录
            self.assertEqual(kb.count(), before, "导出目录被扫描不得回灌知识库")
            kb2 = KnowledgeStore(os.path.join(tmp, "kb2.db"))
            self.assertEqual(kb2.count(), 0, "也不得自动新建知识（显式 import_markdown 是唯一入口）")

class TestReviewVersionConstraint(unittest.TestCase):
    def test_confirmed_does_not_survive_new_evidence_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            kb, nid = rich_kb(os.path.join(tmp, "kb.db"))
            kb.record_baseline({"ev:aaa": "sha-a1"})
            q = kb.scan_dependencies({"ev:aaa": "sha-a1"})
            self.assertEqual([x for x in q if x["claim_idx"] == 0], [],
                             "绑定当前版本 → 不待复核")
            q2 = kb.scan_dependencies({"ev:aaa": "sha-a9"})  # 依据内容再变
            self.assertTrue(any(x["claim_idx"] == 0 for x in q2),
                            "旧审定不继承新版本：必须重新待复核（F4-02）")

    def test_attach_marks_stale_claim(self):
        from domimap.graph import Graph
        from domimap.search import Searcher
        with tempfile.TemporaryDirectory() as tmp:
            kb, nid = rich_kb(os.path.join(tmp, "kb.db"))
            kb.record_baseline({"ev:aaa": "sha-a1"})
            g = Graph.load(os.path.join(HERE, "out_shared", "graph.json"))
            s = Searcher(g)
            s.attach_knowledge(kb, current_digests={"ev:aaa": "sha-a9"})
            node = s.extra["kn:" + nid]
            self.assertTrue(node["meta"]["claims"][0].get("stale"),
                            "依据已变的已审 claim 检索面必须标 stale")

if __name__ == "__main__":
    unittest.main()
