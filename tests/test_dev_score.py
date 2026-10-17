"""dev_score 契约（comparison-dev-diagnosis）：命中判定/负例/分层/归因/确定性。"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "benchmarks"))

from runners import dev_score as ds  # noqa: E402


def rec(system, qid, top5, error_class="ok"):
    return {"system": system, "question_id": qid, "top5": top5,
            "error_class": error_class, "run_id": "r-%s-%s" % (system, qid)}


QUESTIONS = [
    {"id": "q1", "category": "code_location", "query": "改价"},
    {"id": "q2", "category": "cross_repo_trace", "query": "跨"},
    {"id": "q3", "category": "negative", "query": "不存在"},
    {"id": "q4", "category": "locator_diagnostic", "query": "标题"},
]
GOLD = [
    {"id": "q1", "families": ["fA"], "gold_paths": ["fA/src/A.java"],
     "disposition": "answer", "category": "code_location"},
    {"id": "q2", "families": ["fA", "fB"], "gold_paths": ["fA/m/X.xml", "fB/m/Y.xml"],
     "disposition": "answer", "category": "cross_repo_trace"},
    {"id": "q3", "families": [], "gold_paths": [], "disposition": "abstain",
     "category": "negative"},
    {"id": "q4", "families": ["fA"], "gold_paths": ["fA/doc.md"],
     "disposition": "answer", "category": "locator_diagnostic"},
]


class TestDevScore(unittest.TestCase):
    def test_hit_at_5_semantics(self):
        self.assertTrue(ds.hit_at_5(["fA/x", "fA/src/A.java"], ["fA/src/A.java"]))
        self.assertFalse(ds.hit_at_5(["fA/src/A.java"], ["fB/src/A.java"]))
        self.assertFalse(ds.hit_at_5(["fA/a", "fA/b", "fA/c", "fA/d", "fA/e", "fA/src/A.java"],
                                     ["fA/src/A.java"]), "第 6 位不算 Hit@5")

    def test_matrix_and_negatives(self):
        records = [
            rec("domimap", "q1", ["fA/src/A.java"]),
            rec("domimap", "q2", ["fA/m/X.xml"]),
            rec("domimap", "q3", []),                      # 负例空=正确
            rec("domimap", "q4", ["fA/other.md"]),          # miss
            rec("cbm", "q3", ["fB/anything"]),              # 负例非空=错误
        ]
        matrix, misses = ds.score(records, QUESTIONS, GOLD)
        self.assertEqual(matrix["domimap"]["code_location"], [1, 1])
        self.assertEqual(matrix["domimap"]["cross_repo_trace"], [1, 1])
        self.assertEqual(matrix["domimap"]["negative"], [1, 1])
        self.assertEqual(matrix["domimap"]["locator_diagnostic"], [0, 1])
        self.assertEqual(matrix["cbm"]["negative"], [0, 1])
        miss_ids = {m["id"] for m in misses}
        self.assertEqual(miss_ids, {"q4"})

    def test_miss_only_collected_for_domimap(self):
        records = [rec("cbm", "q1", ["fB/elsewhere"])]
        _m, misses = ds.score(records, QUESTIONS, GOLD)
        self.assertEqual(misses, [])

    def test_determinism(self):
        records = [rec("domimap", "q1", ["fA/src/A.java"]),
                   rec("domimap", "q2", ["fB/m/Y.xml"])]
        m1, miss1 = ds.score(list(records), QUESTIONS, GOLD)
        m2, miss2 = ds.score(list(records), QUESTIONS, GOLD)
        self.assertEqual(m1, m2)
        self.assertEqual(miss1, miss2)


if __name__ == "__main__":
    unittest.main()
