"""gold 核验契约（comparison-dev-gold-review）：三值裁决强制理由、fix 需查询覆写、
drop 不回填、keep 的 gold 路径仍存在。"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "benchmarks"))

from runners import gold_review as gr  # noqa: E402

ROWS = [
    {"id": "q1", "category": "code_location", "query": "赵东辉 处理类",
     "gold_paths": ["famA/src/A.java"], "facts": ["f"], "disposition": "answer",
     "excerpts": []},
    {"id": "q2", "category": "doc", "query": "导航壳",
     "gold_paths": ["famA/shell.html"], "facts": ["f"], "disposition": "answer",
     "excerpts": []},
]
QUESTIONS = [{"id": "q1", "category": "code_location", "query": "赵东辉 处理类"},
             {"id": "q2", "category": "doc", "query": "导航壳"}]
GOLD = [{"id": "q1", "families": ["famA"], "gold_paths": ["famA/src/A.java"]},
        {"id": "q2", "families": ["famA"], "gold_paths": ["famA/shell.html"]}]


class TestGoldReview(unittest.TestCase):
    def test_verdict_requires_reason(self):
        with self.assertRaises(ValueError):
            gr.apply_verdicts(ROWS, {"q1": {"verdict": "keep"}, "q2": {"verdict": "drop"}},
                              QUESTIONS, GOLD)

    def test_fix_requires_query_override(self):
        with self.assertRaises(ValueError):
            gr.apply_verdicts(ROWS, {"q1": {"verdict": "fix", "reason": "x"},
                                     "q2": {"verdict": "drop", "reason": "y"}},
                              QUESTIONS, GOLD)

    def test_drop_removed_and_fix_overrides_query(self):
        keep_q, keep_g, review = gr.apply_verdicts(
            ROWS,
            {"q1": {"verdict": "fix", "reason": "剔除作者人名",
                    "query_override": "处理类 位置"},
             "q2": {"verdict": "drop", "reason": "导航壳无实质文本"}},
            QUESTIONS, GOLD)
        self.assertEqual([q["id"] for q in keep_q], ["q1"])
        self.assertEqual(keep_q[0]["query"], "处理类 位置")
        self.assertEqual(keep_g[0]["gold_paths"], ["famA/src/A.java"])
        self.assertEqual(review[1]["verdict"], "drop")

    def test_excerpt_missing_file_reported(self):
        text = gr.excerpt("famA", "no/such.file", "事实")
        self.assertEqual(text, "<文件不存在>")

    def test_excerpt_finds_fact_context(self):
        base = tempfile.mkdtemp(prefix="dm-gr-")
        path = os.path.join(base, "doc.md")
        open(path, "w", encoding="utf-8").write("前文。改价必须审核：单日限额。后文。")
        from runners import gold_review as g
        g._root_of = lambda fam: base
        text = g.excerpt("famA", "doc.md", "改价必须审核")
        self.assertIn("单日限额", text)


if __name__ == "__main__":
    unittest.main()
