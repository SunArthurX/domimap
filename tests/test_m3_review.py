"""M3.3 依赖失效复核（AC-R06-01/02）。"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from domimap.knowledge import KnowledgeStore  # noqa: E402

C1 = {"type": "decision", "statement": "s1", "evidence": ["ev:aaa"], "scope": "A"}
C2 = {"type": "implementation", "statement": "s2", "evidence": ["ev:bbb"], "scope": "B"}

def mk(tmp):
    kb = KnowledgeStore(os.path.join(tmp, "kb.db"))
    nid = kb.submit(body="双陈述笔记", claims=[C1, C2], idempotency_key="rv1")["note_id"]
    kb.record_baseline({"ev:aaa": "sha-a1", "ev:bbb": "sha-b1"})
    return kb, nid

class TestReviewQueue(unittest.TestCase):
    def test_only_affected_claim_queued_no_dup(self):
        with tempfile.TemporaryDirectory() as tmp:
            kb, nid = mk(tmp)
            q = kb.scan_dependencies({"ev:aaa": "sha-a1", "ev:bbb": "sha-b2"})  # 仅 e2 变
            self.assertEqual(len(q), 1, "只有依据变化的陈述入队")
            self.assertEqual((q[0]["note_id"], q[0]["claim_idx"]), (nid, 1))
            self.assertEqual((q[0]["old_sha"], q[0]["new_sha"]), ("sha-b1", "sha-b2"))
            self.assertIn("actions", q[0])
            q2 = kb.scan_dependencies({"ev:aaa": "sha-a1", "ev:bbb": "sha-b2"})  # 重复扫描
            self.assertEqual(len(q2), 1, "同摘要重复扫描不产生重复条目（仍待复核≠翻倍）")
            self.assertEqual((q2[0]["note_id"], q2[0]["claim_idx"], q2[0]["new_sha"]),
                             (q[0]["note_id"], q[0]["claim_idx"], q[0]["new_sha"]))

    def test_confirm_binds_new_evidence_and_clears(self):
        with tempfile.TemporaryDirectory() as tmp:
            kb, nid = mk(tmp)
            kb.scan_dependencies({"ev:aaa": "sha-a1", "ev:bbb": "sha-b2"})
            kb.confirm_review(nid, 1, new_evidence=["ev:bbb", "ev:b2-new"], new_sha="sha-b2")
            q = kb.scan_dependencies({"ev:aaa": "sha-a1", "ev:bbb": "sha-b2"})
            self.assertEqual([x for x in q if x["claim_idx"] == 1], [], "确认绑定后该陈述不再待复核")
            c = kb.get(nid)["claims"][1]
            self.assertEqual(c["state"], "confirmed")
            self.assertEqual(c["evidence"], ["ev:bbb", "ev:b2-new"])

    def test_touch_does_not_refresh_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            kb, nid = mk(tmp)
            kb.scan_dependencies({"ev:aaa": "sha-a1", "ev:bbb": "sha-b2"})
            kb.touch_note(nid)   # 使用/点击
            kb.touch_note(nid)
            q = kb.scan_dependencies({"ev:aaa": "sha-a1", "ev:bbb": "sha-b2"})
            self.assertEqual(len(q), 1, "点击与频率不消除待复核、不刷新真实性")
            c = kb.get(nid)["claims"][1]
            self.assertNotEqual(c["state"], "confirmed")

    def test_withdrawn_not_queued(self):
        with tempfile.TemporaryDirectory() as tmp:
            kb, nid = mk(tmp)
            kb.withdraw(nid)
            q = kb.scan_dependencies({"ev:aaa": "sha-a2", "ev:bbb": "sha-b2"})
            self.assertEqual(q, [], "已撤回不入复核队列")

if __name__ == "__main__":
    unittest.main()
