"""R04-02 语义：MENTIONS/领域归属不冒充因果；路径强度不高于最弱边。

此前（漂移审计 §3 R04 行）：`Graph.impact` 反向遍历不过滤边类型——文档 MENTIONS 表、领域 BELONGS_TO
都算"被依赖"；`scenario.dep_cnt` 同样计数；全库无最弱边概念。
"""
import os
import subprocess
import sys
import tempfile
import unittest

from domimap import mcp
from domimap.graph import Graph
from domimap.service import AppService

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _g():
    g = Graph()
    g.add_node("tbl:t_order", "Table", "t_order", "ddl/t_order.sql", {})
    g.add_node("doc:(root):docs/PRD.md", "Doc", "PRD.md", "docs/PRD.md", {"text": "改价流程说明 t_order"})
    g.add_edge("doc:(root):docs/PRD.md", "tbl:t_order", "MENTIONS", "AMBIGUOUS", "doc:lexical")
    g.add_node("dom:订单域", "Domain", "订单域", "seeds.json", {})
    g.add_edge("tbl:t_order", "dom:订单域", "BELONGS_TO", "INFERRED", "seed")
    g.add_node("mth:s:OrderMapper.updatePrice#2", "Method", "updatePrice", "s/OrderMapper.java", {})
    g.add_node("sql:s:OrderMapper.updatePrice", "SqlStmt", "OrderMapper.updatePrice", "s/OrderMapper.xml", {})
    g.add_edge("mth:s:OrderMapper.updatePrice#2", "sql:s:OrderMapper.updatePrice", "CALLS_SQL", "EXTRACTED", "synth:mybatis")
    g.add_edge("sql:s:OrderMapper.updatePrice", "tbl:t_order", "WRITES", "EXTRACTED", "synth:mybatis")
    g.add_node("mth:s:OrderController.changePrice#1", "Method", "changePrice", "s/OrderController.java", {})
    g.add_edge("mth:s:OrderController.changePrice#1", "mth:s:OrderMapper.updatePrice#2", "CALLS", "AMBIGUOUS", "lite")
    return g


class TestImpactSemantics(unittest.TestCase):
    def setUp(self):
        self.g = _g()
        d = tempfile.TemporaryDirectory(prefix="dm-r04-")
        self.addCleanup(d.cleanup)
        self.gp = os.path.join(d.name, "graph.json")
        self.g.save(self.gp)

    def test_mentions_and_domain_are_not_reverse_dependencies(self):
        start, deps = self.g.impact("t_order", depth=3)
        kinds = {k for _, k, _, _ in deps}
        self.assertNotIn("MENTIONS", kinds, "文档提及不是因果依赖（roadmap M2）")
        self.assertNotIn("BELONGS_TO", kinds, "领域归属不是因果依赖")
        self.assertIn("WRITES", kinds)
        self.assertIn("CALLS_SQL", kinds)
        self.assertIn("CALLS", kinds)

    def test_path_strength_is_the_weakest_edge(self):
        start, deps = self.g.impact("t_order", depth=3)
        by_kind = {k: s for _, k, _, s in deps}
        # CALLS_SQL 直接写表：EXTRACTED；CALLS 边是 AMBIGUOUS → 该路径强度为 AMBIGUOUS（最弱边）
        self.assertEqual(by_kind["WRITES"], "EXTRACTED")
        self.assertEqual(by_kind["CALLS_SQL"], "EXTRACTED")
        self.assertEqual(by_kind["CALLS"], "AMBIGUOUS", "路径强度不得高于最弱边")

    def test_service_and_entries_expose_strength_and_partial(self):
        svc = AppService(self.gp)
        r = svc.impact("t_order", depth=3)
        self.assertTrue(all("strength" in d for d in r["deps"]))
        calls = [d for d in r["deps"] if d["kind"] == "CALLS"]
        self.assertEqual(calls[0]["strength"], "AMBIGUOUS")
        out = json = mcp.Server(self.gp).call("kg_impact", {"symbol": "t_order", "depth": 3})
        self.assertFalse(out["isError"])
        self.assertIn("AMBIGUOUS", out["content"][0]["text"], "MCP 输出可见最弱边强度")
        p = subprocess.run([sys.executable, "-B", "-m", "domimap", "impact", "t_order", "-g", self.gp,
                            "--depth", "3"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("AMBIGUOUS", p.stdout, "CLI 输出可见最弱边强度")

    def test_scenario_dep_cnt_ignores_lexical_and_domain_edges(self):
        from domimap.scenario import scenario_trb
        from domimap.search import Searcher
        text = scenario_trb(self.g, Searcher(self.g), "t_order")
        # 表卡片"被依赖 N 处"只数因果反向边：WRITES 1 条；MENTIONS（文档提及）与 BELONGS_TO 不计
        self.assertIn("被依赖 1 处", text, text)
        self.assertNotIn("被依赖 2 处", text)


if __name__ == "__main__":
    unittest.main()
