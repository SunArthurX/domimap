"""合成多仓规模门禁：超预算必须失败。完整 200 仓由 scripts/scale_gate.py 实跑。"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from scripts.scale_gate import SYNTHETIC_BUDGETS, check, generate, measure  # noqa: E402


class TestScaleGate(unittest.TestCase):
    def test_over_budget_is_a_violation(self):
        report = {"build_seconds": 1, "graph_bytes": 10, "query_seconds": 0.1}
        self.assertEqual(check(report, SYNTHETIC_BUDGETS), [])
        report["graph_bytes"] = SYNTHETIC_BUDGETS["graph_bytes"] + 1
        self.assertTrue(check(report, SYNTHETIC_BUDGETS))

    def test_four_repo_build_stays_inside_the_synthetic_budget(self):
        tmp = tempfile.mkdtemp(prefix="dm-scale-")
        self.addCleanup(shutil.rmtree, tmp)
        ws = generate(4, os.path.join(tmp, "ws"))
        report = measure(ws, os.path.join(tmp, "out"), jobs=2)
        self.assertEqual(report["repos"], 4)
        self.assertGreater(report["nodes"], 0)
        self.assertEqual(check(report, SYNTHETIC_BUDGETS), [], report)


if __name__ == "__main__":
    unittest.main()
