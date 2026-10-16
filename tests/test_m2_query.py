"""M2.1 首片：核心查询领域词表扩展（公共语义起点，目标 tiny q5 纯中文召回）。"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from domimap import batch  # noqa: E402
from domimap.graph import load_seeds  # noqa: E402
from domimap.search import Searcher  # noqa: E402

OUT = os.path.join(HERE, "out_m2")
SEEDS = load_seeds(os.path.join(ROOT, "domimap", "seeds.json"))

_g = None
def G():
    global _g
    if _g is None:
        roots = batch.discover_roots(os.path.join(HERE, "fixtures"))
        _g, _, _ = batch.build_many(roots, OUT, force=True, merged_name="fixtures")
    return _g

class TestDomainExpansionInCoreQuery(unittest.TestCase):
    def test_pure_chinese_query_hits_with_seads(self):
        s = Searcher(G())
        r = s.query("价格同步监听", top_k=5, expand=False, seeds=SEEDS)
        names = " ".join(n["name"] for n in r["seeds"])
        self.assertFalse(r["refused"], "领域扩展后不应拒答")
        self.assertIn("PriceSyncListener", names, names)

    def test_without_seeds_keeps_honest_behaviour(self):
        s = Searcher(G())
        r = s.query("价格同步监听", top_k=5, expand=False)
        self.assertTrue(r["refused"] or
                        "PriceSyncListener" not in " ".join(n["name"] for n in r["seeds"]),
                        "不带 seeds 的对照行为不变（扩展是显式语义）")

if __name__ == "__main__":
    unittest.main()
