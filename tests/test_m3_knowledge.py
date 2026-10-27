"""M3.1 知识事务契约（AC-R05-01）：幂等/冲突/防覆盖/历史/撤回/中断/并发。"""
import os
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from domimap.knowledge import ConflictError, KnowledgeStore  # noqa: E402

CLAIMS = [{"type": "decision", "statement": "改价需带 price_version 乐观锁",
           "evidence": ["doc:mini:docs/改价需求PRD.md"], "scope": "订单域"}]

def store(tmp):
    return KnowledgeStore(os.path.join(tmp, "kb.db"))

class TestKnowledgeTxn(unittest.TestCase):
    def test_create_idempotent_and_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = store(tmp)
            r1 = s.submit(body="改价并发结论 A", claims=CLAIMS, idempotency_key="k1")
            self.assertEqual(r1["revision"], 1)
            r2 = s.submit(body="改价并发结论 A", claims=CLAIMS, idempotency_key="k1")
            self.assertEqual((r2["note_id"], r2["revision"]), (r1["note_id"], 1), "同键同内容幂等")
            with self.assertRaises(ConflictError):
                s.submit(body="改价并发结论 B", claims=CLAIMS, idempotency_key="k1")

    def test_amend_needs_current_expected_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = store(tmp)
            r = s.submit(body="v1", claims=CLAIMS, idempotency_key="k2")
            with self.assertRaises(ConflictError):
                s.amend(r["note_id"], body="v2", expected_revision=0)  # 旧版本 → 拒绝覆盖
            r2 = s.amend(r["note_id"], body="v2", expected_revision=1)
            self.assertEqual(r2["revision"], 2)
            hist = s.history(r["note_id"])
            self.assertEqual([h["revision"] for h in hist], [1, 2], "历史修订完整保留")

    def test_withdraw_keeps_history_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = store(tmp)
            r = s.submit(body="will withdraw", claims=CLAIMS, idempotency_key="k3")
            s.withdraw(r["note_id"])
            self.assertEqual(s.get(r["note_id"])["status"], "withdrawn")
            self.assertEqual(len(s.history(r["note_id"])), 1, "撤回不清历史")

    def test_txn_interrupt_leaves_no_partial_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = store(tmp)
            s._fail_stage = "pre-commit"
            with self.assertRaises(RuntimeError):
                s.submit(body="crash", claims=CLAIMS, idempotency_key="k4")
            s._fail_stage = None
            self.assertEqual(s.count(), 0, "中断不得留半行")
            r = s.submit(body="retry ok", claims=CLAIMS, idempotency_key="k4")
            self.assertEqual(r["revision"], 1, "中断后重试可用")

    def test_concurrency_distinct_keys_all_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "kb.db")
            errs = []
            def w(i):
                try:
                    KnowledgeStore(path).submit(body="n%d" % i, claims=CLAIMS,
                                                idempotency_key="kc%d" % i)
                except Exception as e:  # noqa: BLE001
                    errs.append(e)
            ts = [threading.Thread(target=w, args=(i,)) for i in range(6)]
            [t.start() for t in ts]; [t.join() for t in ts]
            self.assertFalse(errs, errs)
            self.assertEqual(KnowledgeStore(path).count(), 6)

    def test_concurrent_same_key_single_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "kb.db")
            KnowledgeStore(path)  # init schema
            def w():
                try:
                    KnowledgeStore(path).submit(body="same", claims=CLAIMS, idempotency_key="ks")
                except Exception:  # noqa: BLE001
                    pass
            ts = [threading.Thread(target=w) for _ in range(4)]
            [t.start() for t in ts]; [t.join() for t in ts]
            self.assertEqual(KnowledgeStore(path).count(), 1, "并发同键同内容恰一行")

    def test_inference_accepted_not_extracted(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = store(tmp)
            r = s.submit(body="推断条目", claims=[dict(CLAIMS[0], type="inference")],
                         idempotency_key="k5")
            stmt = s.get(r["note_id"])["claims"][0]["statement"]
            s.accept_claim(r["note_id"], 0, expected_revision=1, statement=stmt)
            c = s.get(r["note_id"])["claims"][0]
            self.assertEqual((c["type"], c["state"]), ("inference", "accepted"))
            self.assertNotEqual(c["type"], "extracted", "接受推断不得变为抽取事实")

if __name__ == "__main__":
    unittest.main()
