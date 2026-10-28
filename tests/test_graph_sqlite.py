"""graph.db 按需读边，查询种子与内存图一致；服务概要卡覆盖入口和表。"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from domimap.graph import Graph, build, load_seeds  # noqa: E402
from domimap.search import Searcher  # noqa: E402

MINI = os.path.join(HERE, "fixtures", "mini")
SEEDS = os.path.join(ROOT, "domimap", "seeds.json")


class TestGraphDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dm-gdb-")
        self.addCleanup(shutil.rmtree, self.tmp)
        self.g, _ = build(MINI, self.tmp)
        self.db = os.path.join(self.tmp, "graph.db")
        self.json = os.path.join(self.tmp, "graph.json")

    def tearDown(self):
        store = getattr(getattr(self, "lazy", None), "_edge_store", None)
        if store is not None:
            store.close()

    def test_publish_writes_sqlite_and_lazy_neighbors_match(self):
        self.assertTrue(os.path.exists(self.db), self.tmp)
        eager = Graph.load(self.json)
        self.lazy = Graph.load(self.json, lazy_edges=True)
        self.assertEqual(set(self.lazy.nodes), set(eager.nodes))
        self.assertEqual(len(self.lazy.edges), len(eager.edges))
        nid = "mth:order-service:OrderController.changePrice(PriceReq)"
        self.assertEqual(self.lazy.neighbors(nid), eager.neighbors(nid))
        seeds = load_seeds(SEEDS)
        a = [n["id"] for n in Searcher(eager).query("订单改价", seeds=seeds)["seeds"]]
        b = [n["id"] for n in Searcher(self.lazy).query("订单改价", seeds=seeds)["seeds"]]
        self.assertEqual(a, b)
        eager_store = getattr(eager, "_edge_store", None)
        if eager_store:
            eager_store.close()

    def test_service_card_lists_routes_and_tables(self):
        card = self.g.service_card("order-service")
        self.assertIsNotNone(card)
        self.assertTrue(any("POST" in r and "/trade/" in r for r in card["routes"]), card["routes"])
        self.assertIn("t_order", card["tables"])
        self.assertTrue(card["topics"], card)
        self.assertIsNone(self.g.service_card("不存在的服务"))


if __name__ == "__main__":
    unittest.main()
