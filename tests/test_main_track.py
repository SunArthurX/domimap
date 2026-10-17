"""主轨运行器骨架契约（comparison-maintrack-runner）。"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "benchmarks"))

from runners.main_track import (DryRunHost, MainTrackRunner, STATUS_BUDGET_TOKENS,
                                STATUS_BUDGET_TOOL, TrackBudget)  # noqa: E402

QUESTIONS = [{"id": "q1", "query": "订单改价入口在哪里"},
             {"id": "q2", "query": "迁移说明的回滚条件"},
             {"id": "q3", "query": "表 X 哪些服务读写"}]


class TestMainTrackRunner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dm-mt-")

    def test_fresh_session_per_question(self):
        host = DryRunHost()
        records = MainTrackRunner(self.tmp).run("domimap", host, QUESTIONS, TrackBudget())
        self.assertEqual(len(records), 3)
        sids = [r["session_id"] for r in records]
        self.assertEqual(len(set(sids)), 3, "每题必须全新会话")
        self.assertEqual(len(host.sessions), 3)

    def test_tool_budget_hard_cap(self):
        host = DryRunHost(turns=5, tools_per_turn=10)
        records = MainTrackRunner(self.tmp).run(
            "domimap", host, QUESTIONS,
            TrackBudget(wall_clock_s=60, max_tool_calls=24, max_new_tokens=10 ** 6,
                        max_input=10 ** 6, max_output=10 ** 6))
        for r in records:
            self.assertEqual(r["status"], STATUS_BUDGET_TOOL)
            self.assertGreater(r["ledger"]["tool_calls"], 24)
            self.assertLessEqual(r["ledger"]["tool_calls"], 24 + 10,
                                 "超限即停：不再继续回合")

    def test_token_budget_hard_cap(self):
        host = DryRunHost(turns=5, tokens_per_turn=(50000, 2000))
        records = MainTrackRunner(self.tmp).run(
            "domimap", host, QUESTIONS[:1],
            TrackBudget(wall_clock_s=60, max_tool_calls=10 ** 6, max_new_tokens=24000,
                        max_input=120000, max_output=8000))
        self.assertEqual(records[0]["status"], STATUS_BUDGET_TOKENS)

    def test_ledger_and_transcript_complete(self):
        records = MainTrackRunner(self.tmp).run("domimap", DryRunHost(), QUESTIONS,
                                                TrackBudget())
        for r in records:
            self.assertTrue(os.path.isfile(r["transcript_path"]))
            payload = json.load(open(r["transcript_path"], encoding="utf-8"))
            self.assertEqual(payload["run_id"], r["run_id"])
            self.assertTrue(payload["transcript"])
            for key in ("tool_calls", "tokens_in", "tokens_out", "secs"):
                self.assertIn(key, r["ledger"])
            self.assertTrue(r["run_id"].startswith("mt-"))

    def test_synthetic_flag_on_dryrun(self):
        records = MainTrackRunner(self.tmp).run("domimap", DryRunHost(), QUESTIONS[:1],
                                                TrackBudget())
        self.assertTrue(records[0]["synthetic"], "DryRunHost 产物必须标注 synthetic")

    def test_gold_fields_rejected(self):
        bad = [{"id": "q1", "query": "x", "gold": ["p"]}]
        with self.assertRaises(ValueError):
            MainTrackRunner(self.tmp).run("domimap", DryRunHost(), bad, TrackBudget())


if __name__ == "__main__":
    unittest.main()
