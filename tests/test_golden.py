"""golden 测试：5 个 synthesizer + 领域打标 + 检索 + 影响面 的最小正确性契约。

跑法：cd domimap && python3 -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from domimap.graph import build  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "mini")
_OUTPUT = tempfile.TemporaryDirectory(prefix="domimap-golden-")
unittest.addModuleCleanup(_OUTPUT.cleanup)
OUT = _OUTPUT.name

_g = None
def G():
    global _g
    if _g is None:
        _g, _cov = build(FIX, OUT, os.path.join(ROOT, "domimap", "seeds.json"))
    return _g

def find(g, kind, name=None):
    return [n for n in g.nodes.values() if n["kind"] == kind and (name is None or name in n["name"])]

def has_edge(g, src_sub, kind, dst_sub):
    return any(src_sub in e["src"] and e["kind"] == kind and dst_sub in e["dst"] for e in g.edges)

class TestSpringRoute(unittest.TestCase):
    def test_route_node_and_handles(self):
        g = G()
        routes = find(g, "Route")
        self.assertTrue(any("POST /trade/price" == n["name"] for n in routes), [n["name"] for n in routes])
        self.assertTrue(any("GET /item/list" == n["name"] for n in routes))
        self.assertTrue(has_edge(g, "mth:order-service:OrderController.changePrice#1", "HANDLES", "route:order-service:POST /trade/price"))

class TestMyBatis(unittest.TestCase):
    def test_sqlstmt_and_table_bridge(self):
        g = G()
        self.assertTrue(find(g, "SqlStmt", "OrderMapper.updatePrice"))
        self.assertTrue(has_edge(g, "mth:order-service:OrderMapper.updatePrice#2", "CALLS_SQL", "sql:order-service:OrderMapper.updatePrice"))
        self.assertTrue(has_edge(g, "sql:order-service:OrderMapper.updatePrice", "WRITES", "tbl:t_order"),
                        "mapper UPDATE 应产出 WRITES 边")
        self.assertTrue(has_edge(g, "sql:order-service:OrderMapper.selectById", "READS", "tbl:t_order"))

class TestRocketMQ(unittest.TestCase):
    def test_pub_sub_edges(self):
        g = G()
        self.assertTrue(find(g, "Topic", "trade-price-changed"))
        self.assertTrue(has_edge(g, "mth:order-service:OrderPriceService.changePrice#2", "PUBLISHES", "topic:trade-price-changed"))
        self.assertTrue(has_edge(g, "topic:trade-price-changed", "SUBSCRIBES", "cls:PriceSyncListener") or
                        has_edge(g, "topic:trade-price-changed", "SUBSCRIBES", "svc:item-service"))

class TestDubbo(unittest.TestCase):
    def test_rpc_edge(self):
        g = G()
        # item-service 经 @DubboReference 消费 OrderPriceService（provider 由 @Service 存根近似）
        rpc = [e for e in g.edges if e["kind"] == "RPC"]
        self.assertTrue(any("item-service" in e["src"] for e in rpc), rpc)

class TestCrossEnd(unittest.TestCase):
    def test_page_to_route(self):
        g = G()
        self.assertTrue(find(g, "Page", "/trade/price"))
        self.assertTrue(has_edge(g, "page:pages:/trade/price", "ROUTES_TO", "route:order-service:POST /trade/price"))

class TestDomain(unittest.TestCase):
    def test_service_domain_and_shared(self):
        g = G()
        self.assertEqual(g.nodes["svc:order-service"]["meta"].get("domain"), "订单域")
        self.assertEqual(g.nodes["svc:item-service"]["meta"].get("domain"), "商品域")
        m = g.domain_map()
        self.assertIn("订单域", m)
        self.assertTrue("order-service" in m["订单域"]["services"])

class TestSearch(unittest.TestCase):
    def test_query_chinese_and_english(self):
        from domimap.search import Searcher
        s = Searcher(G())
        r = s.query("订单改价 防并发")
        self.assertFalse(r["refused"])
        self.assertIn("t_order", r["text"] + json_dump(r))
        r2 = s.query("price_version")
        self.assertFalse(r2["refused"])
        self.assertTrue(any(n["kind"] in {"Column", "SqlStmt"} for n in r2["seeds"]), [n["kind"] for n in r2["seeds"]])

    def test_refusal_when_no_match(self):
        from domimap.search import Searcher
        r = Searcher(G()).query("完全不存在的词zzzqqq")
        self.assertTrue(r["refused"])

class TestImpact(unittest.TestCase):
    def test_reverse_dependency(self):
        g = G()
        start, deps = g.impact("t_order")
        self.assertTrue(start)
        names = [d[0]["name"] for d in deps]
        self.assertTrue(any("updatePrice" in x or "OrderMapper" in x for x in names), names)

def json_dump(r):
    import json
    return json.dumps([n["name"] for n in r["seeds"]], ensure_ascii=False)

class TestMethodCalls(unittest.TestCase):
    def test_controller_to_dao_calls(self):
        g = G()
        # D4 修复后（m1-identity-sources）：Method id 类限定，跨类同名不再共点——
        # OrderController.changePrice --CALLS--> OrderPriceService.changePrice（此前因共点丢失）
        # OrderPriceService.changePrice --CALLS--> OrderMapper.updatePrice（orderMapper 调用）
        self.assertTrue(has_edge(g, "mth:order-service:OrderController.changePrice#1", "CALLS",
                                 "mth:order-service:OrderPriceService.changePrice#2"),
                        "跨类同名方法调用边必须存在（D4 修复回归）")
        self.assertTrue(has_edge(g, "mth:order-service:OrderPriceService.changePrice#2", "CALLS",
                                 "mth:order-service:OrderMapper.updatePrice#2"),
                        "changePrice --CALLS--> updatePrice（orderMapper 调用）")
        calls = [e for e in g.edges if e["kind"] == "CALLS"]
        self.assertEqual(len(calls), 2, "夹具内可解析的调用边应为 2 条（新增夹具时同步本契约）")
        self.assertEqual(calls[0]["conf"], "INFERRED")
        self.assertEqual(calls[0]["prov"], "synth:java-call")


if __name__ == "__main__":
    unittest.main(verbosity=2)
