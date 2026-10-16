"""M1.2 解析精度契约：重载/字段别名/空方法/嵌套边界（先红后绿）。"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from domimap import lite_scan  # noqa: E402
from domimap.graph import Graph, load_seeds  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "precision")
SEEDS = os.path.join(ROOT, "domimap", "seeds.json")

def build():
    R = lite_scan.scan_repo(FIX, repo_label="precision")
    g = Graph()
    g.build_from_records(R, load_seeds(SEEDS))
    return g, R

class TestOverload(unittest.TestCase):
    def test_overloads_are_distinct_nodes(self):
        g, _ = build()
        ids = {n["id"] for n in g.nodes.values()
               if n["kind"] == "Method" and n["name"] == "changePrice"
               and ":Overload." in n["id"]}
        self.assertEqual(ids, {"mth:precision:Overload.changePrice#2",
                               "mth:precision:Overload.changePrice#1"}, ids)

    def test_ambiguous_dispatch_not_silent_single_edge(self):
        g, _ = build()
        edges = [e for e in g.edges if e["kind"] == "CALLS"
                 and e["src"] == "mth:precision:Overload.caller#0"]
        self.assertTrue(edges, "caller 的重载调用应有边（歧义可见）")
        self.assertTrue(all(e["conf"] == "AMBIGUOUS" for e in edges),
                        "重载目标不可判定时必须 AMBIGUOUS，不得默取第一个：%s" % edges)
        dsts = {e["dst"] for e in edges}
        self.assertIn("mth:precision:Overload.changePrice#2", dsts)
        self.assertIn("mth:precision:Overload.changePrice#1", dsts)

class TestFieldAlias(unittest.TestCase):
    def test_field_typed_receiver_resolves(self):
        g, _ = build()
        edges = [e for e in g.edges if e["kind"] == "CALLS"
                 and e["src"] == "mth:precision:FieldAlias.run#0"]
        self.assertTrue(edges, "字段声明类型应参与接收者解析")
        self.assertEqual({e["conf"] for e in edges}, {"AMBIGUOUS"},
                         "目标类存在重载 → AMBIGUOUS（字段别名解析本身生效即可）")
        self.assertEqual({e["dst"] for e in edges},
                         {"mth:precision:Overload.changePrice#2",
                          "mth:precision:Overload.changePrice#1"})

class TestEmptyAndNested(unittest.TestCase):
    def test_empty_method_node_exists(self):
        g, _ = build()
        self.assertIn("mth:precision:EmptyAndNested.doNothing#0", g.nodes)

    def test_lambda_calls_not_owned_by_outer(self):
        g, R = build()
        outer_edges = [e for e in g.edges if e["kind"] == "CALLS"
                       and e["src"] == "mth:precision:EmptyAndNested.outer#0"]
        self.assertEqual(outer_edges, [], "lambda/匿名内调用不得归属外层方法（假归属）")
        self.assertTrue(any("lambda" in s.get("reason", "") or "匿名" in s.get("reason", "")
                            for s in R["coverage"]["skipped"]),
                        "保守跳过必须显式记录：%s" % R["coverage"]["skipped"])

if __name__ == "__main__":
    unittest.main()
