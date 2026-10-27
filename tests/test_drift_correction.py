"""drift-correction-c0：纠正状态登记的回归（status bookkeeping）。

审计纠正后必须长期成立：受影响案例与任务回到 verified 时携带新证据文件；
旧 activated 决定的失效记录留档；C0 基线归档完整。
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _load(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


class TestDriftCorrectionBookkeeping(unittest.TestCase):
    def setUp(self):
        # 守账对象是本地审计/闭环工件（out/drift-audit-2026-10-26、out/dev-ws、out/verification）：
        # 不入 git，CI/新克隆没有——按仓库既有模式跳过，本地存在时全量断言。
        for rel in ("out/drift-audit-2026-10-26/correction", "out/dev-ws"):
            if not os.path.isdir(os.path.join(ROOT, rel)):
                self.skipTest("本地审计工件不在（CI/新克隆）：%s" % rel)

    def test_corrected_cases_verified_with_evidence(self):
        progress = _load("specs/progress.json")
        for cid in ("AC-R15-01", "AC-R15-02", "AC-R15-03", "AC-R15-04", "AC-R15-05"):
            case = progress["cases"][cid]
            self.assertEqual(case["state"], "verified", cid)
            for ev in case["evidence"]:
                self.assertTrue(os.path.exists(os.path.join(ROOT, ev)),
                                "%s 证据缺失：%s" % (cid, ev))

    def test_old_activation_invalidation_retained(self):
        p = os.path.join(ROOT, "out/dev-ws",
                         "activation-ccf1ee268b695abbf2cd-invalidated.json")
        self.assertTrue(os.path.exists(p), "旧启用决定的失效记录必须留档")
        d = _load("out/dev-ws/activation-ccf1ee268b695abbf2cd-invalidated.json")
        self.assertEqual(d["invalidation"]["decision_was"], "activated")
        self.assertTrue(d["invalidation"]["db_row_preserved"])

    def test_c0_baseline_archive_complete(self):
        base = os.path.join(ROOT, "out/drift-audit-2026-10-26/correction")
        for name in ("baseline-handoff-2026-10-26.md", "baseline-working-tree.patch",
                     "baseline-untracked.txt",
                     "baseline-real-workspace-artifacts.sha256"):
            self.assertTrue(os.path.exists(os.path.join(base, name)), name)

    def test_new_activation_recorded_with_lineage(self):
        ids = open(os.path.join(ROOT, "out/dev-ws/correction/loop-v3-ids.txt"),
                   encoding="utf-8").read()
        self.assertIn("BASELINE_RUN=rp:cdcf888fa0b86cc2", ids)
        self.assertIn("CANDIDATE_RUN=rp:ab3f271dff7bbc5f", ids)
        trace = _load("out/dev-ws/correction/evolution-trace-v3.json")
        decisions = [i["decision"] for i in trace["improvements"]]
        self.assertIn("activated", decisions)


if __name__ == "__main__":
    unittest.main()
