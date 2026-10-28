"""P1 增量 golden 测试：多仓发现合并（跨仓 RPC）/ 通用 MQ / JPA / 增量 no-op / 场景 A/B。"""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIXROOT = os.path.join(HERE, "fixtures")
sys.path.insert(0, ROOT)

from domimap import batch, scenario  # noqa: E402
from domimap.graph import Graph, load_seeds  # noqa: E402
from domimap.search import Searcher  # noqa: E402

_OUTPUT = tempfile.TemporaryDirectory(prefix="domimap-multi-")
unittest.addModuleCleanup(_OUTPUT.cleanup)
OUT = _OUTPUT.name

def merged_graph():
    roots = batch.discover_roots(FIXROOT)
    g, cov, results = batch.build_many(roots, OUT, force=True, merged_name="fixtures")
    return g, roots, results

_g = None
_roots = None
def G():
    global _g, _roots
    if _g is None:
        _g, _roots, _ = merged_graph()
    return _g

class TestDiscover(unittest.TestCase):
    def test_two_repos_found(self):
        global _roots
        g = G()
        names = [os.path.basename(r) for r in _roots]
        self.assertIn("mini", names, names)
        self.assertIn("repo-belt", names)

class TestCrossRepoRPC(unittest.TestCase):
    def test_rpc_across_repos(self):
        g = G()
        rpc = [e for e in g.edges if e["kind"] == "RPC"]
        self.assertTrue(any("repo-belt" in e["src"] and "mini" in e["dst"] for e in rpc),
                        [(e["src"], e["dst"]) for e in rpc])

class TestGenericMQ(unittest.TestCase):
    def test_kafka_topics_subscribed(self):
        g = G()
        self.assertTrue(any(n["kind"] == "Topic" and n["name"] == "stock-warn" for n in g.nodes.values()))
        self.assertTrue(any(n["name"] == "stock-warn-dlq" for n in g.nodes.values()))

class TestJPA(unittest.TestCase):
    def test_entity_maps_table_and_columns(self):
        g = G()
        self.assertIn("tbl:repo-belt:ware-service:t_ware_stock", g.nodes)
        self.assertIn("col:repo-belt:ware-service:t_ware_stock.sku_code", g.nodes)
        self.assertTrue(any(e["kind"] == "MAPS_TO" and "WareStock" in e["src"] for e in g.edges),
                        "实体类应 MAPS_TO 表")

class TestIncremental(unittest.TestCase):
    def test_second_build_is_noop(self):
        roots = batch.discover_roots(FIXROOT)
        g1, _, r1 = batch.build_many(roots, OUT, force=True, merged_name="fixtures")
        g2, _, r2 = batch.build_many(roots, OUT, merged_name="fixtures")
        self.assertEqual([st for _, st in r2], ["no-op"] * len(roots), r2)
        self.assertIsNone(g2, "无变更不应重建")

class TestScenarioReq(unittest.TestCase):
    def test_req_card_mentions_order_domain(self):
        g = G()
        s = Searcher(g)
        seeds = load_seeds(os.path.join(ROOT, "domimap", "seeds.json"))
        buf = io.StringIO()
        with redirect_stdout(buf):
            card = scenario.scenario_req(g, s, "订单改价 防并发 price_version", seeds)
        self.assertIn("需求定位卡", card)
        self.assertTrue("订单域" in card or "order-service" in card)

class TestScenarioTrb(unittest.TestCase):
    def test_trb_card_has_snippets(self):
        g = G()
        s = Searcher(g)
        card = scenario.scenario_trb(g, s, "price_version 并发 覆盖")
        self.assertIn("排障卡", card)
        self.assertTrue(">" in card, "应包含文档摘句（> 引用行）")

class TestIndexCache(unittest.TestCase):
    def test_cache_roundtrip_and_invalidate(self):
        gp = os.path.join(OUT, "graph.json")
        G().save(gp)
        g1 = Graph.load(gp)
        s1 = Searcher(g1, cache_path=gp + ".idx.json")
        self.assertTrue(os.path.exists(gp + ".idx.db"), "应写出 SQLite 倒排，而不是把 posting 放进 JSON")
        self.assertIsNotNone(getattr(s1, "_idxdb", None))
        s2 = Searcher(Graph.load(gp), cache_path=gp + ".idx.json")   # 应命中缓存
        q = "订单改价 防并发"
        self.assertEqual([n["id"] for n in s1.query(q)["seeds"]], [n["id"] for n in s2.query(q)["seeds"]])
        with open(gp, "a", encoding="utf-8") as f:
            f.write(" ")                                             # mtime/size 变 → 缓存失效
        s3 = Searcher(Graph.load(gp), cache_path=gp + ".idx.json")
        self.assertIsNotNone(getattr(s2, "_idxdb", None))
        self.assertEqual([n["id"] for n in s1.query(q)["seeds"]], [n["id"] for n in s3.query(q)["seeds"]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
