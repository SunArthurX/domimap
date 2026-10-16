"""M2.3：F3 可信上下文 + F4 as_of 时间数据面（AC-F3-01 / AC-F4-01）。"""
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from domimap.context import load_context  # noqa: E402

class TestF3Context(unittest.TestCase):
    def setUp(self):
        self.trusted = tempfile.mkdtemp(prefix="dm-ctx-")
        os.makedirs(os.path.join(self.trusted, "nested"))
        open(os.path.join(self.trusted, "AGENTS.md"), "w").write("# root rules\nbe strict")
        open(os.path.join(self.trusted, "nested", "SOUL.md"), "w").write("# nested persona")

    def test_load_with_hash_and_scope(self):
        out = load_context(self.trusted)
        items = out["items"]
        self.assertEqual([os.path.basename(i["path"]) for i in items], ["AGENTS.md", "SOUL.md"])
        self.assertFalse(out["truncated"])
        self.assertTrue(all(len(i["sha256"]) == 64 and i["size"] > 0 for i in items))

    def test_corpus_rules_rejected(self):
        corpus = tempfile.mkdtemp(prefix="dm-corpus-")
        open(os.path.join(corpus, "AGENTS.md"), "w").write("# malicious")
        with self.assertRaises(PermissionError):
            load_context(corpus, trusted=[self.trusted])

    def test_budget_truncation_explicit(self):
        open(os.path.join(self.trusted, "big.md"), "w").write("x" * 100)
        out = load_context(self.trusted, budget=30)
        self.assertTrue(out["truncated"], "超预算必须显式标记，不得静默截断")
        self.assertTrue(out["items"] or out["dropped"])

class TestF4AsOf(unittest.TestCase):
    def test_first_seen_by_content_copy_not_refreshed(self):
        from domimap.store import EvidenceStore
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(os.path.join(tmp, "store.db"))
            p = os.path.join(tmp, "a.txt")
            open(p, "w").write("same")
            store.capture_source("r", "r|a.txt", p, "a.txt")
            time.sleep(0.05)
            store.capture_source("r", "r|a.txt", p, "a.txt")  # 重存同内容
            q = os.path.join(tmp, "copy.txt")
            open(q, "w").write("same")
            store.capture_source("r", "r|copy.txt", q, "copy.txt")  # 复制
            rows = {r[0]: r[1] for r in store.db.execute(
                "SELECT sid, first_seen FROM sources")}
            self.assertEqual(rows["r|a.txt"], rows["r|copy.txt"],
                             "复制/重存不得刷新内容最早出现时间（F4）")

    def test_as_of_eligibility_filter(self):
        from domimap.graph import Graph, load_seeds
        from domimap.search import Searcher
        import domimap.lite_scan as ls
        with tempfile.TemporaryDirectory() as tmp:
            ws = os.path.join(tmp, "mini")
            import shutil
            shutil.copytree(os.path.join(HERE, "fixtures", "mini"), ws)
            R = ls.scan_repo(ws, repo_label="mini")
            g = Graph(); g.build_from_records(R, load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
            doc = next(n for n in g.nodes.values() if n["name"] == "改价需求PRD.md")
            doc["meta"]["first_seen"] = 20000000.0  # 晚于 as_of
            r_new = Searcher(g).query("改价需求 PRD", top_k=8, as_of=10000000.0)
            self.assertNotIn("改价需求PRD.md", [n["name"] for n in r_new["seeds"]],
                             "first_seen 晚于 as_of 的资料不具资格（资格先筛选）")

if __name__ == "__main__":
    unittest.main()
