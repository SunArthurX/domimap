"""M4.2 R09-02：框架构造能力矩阵（支持/部分/未知，多 provider 不默取其一）。"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import domimap.lite_scan as ls  # noqa: E402
from domimap.graph import Graph, load_seeds  # noqa: E402

SEEDS = os.path.join(ROOT, "domimap", "seeds.json")

def build_ws(files):
    tmp = tempfile.mkdtemp(prefix="dm-mx-")
    for rel, text in files.items():
        p = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w", encoding="utf-8").write(text)
    R = ls.scan_repo(tmp, repo_label="mx")
    g = Graph(); g.build_from_records(R, load_seeds(SEEDS))
    return g

class TestMatrix(unittest.TestCase):
    def test_dynamic_sql_tables_extracted(self):
        g = build_ws({"a.xml": '<mapper namespace="X"><select id="q">'
                               '<if test="1">SELECT * FROM dyn_t WHERE x=1</if></select></mapper>'})
        self.assertIn("tbl:mx:dyn_t", g.nodes, "动态 SQL 内表必须抽取（声明=支持）")
        self.assertTrue(any(e["kind"] == "READS" and e["dst"] == "tbl:mx:dyn_t" for e in g.edges))

    def test_multi_provider_all_linked_ambiguous(self):
        g = build_ws({
            "svc1/P1.java": "package a;\n@org.apache.dubbo.config.annotation.DubboService\nclass OrderRpc { public Object get(Long id){return null;} }",
            "svc2/P2.java": "package b;\n@org.apache.dubbo.config.annotation.DubboService\nclass OrderRpc { public Object get(Long id){return null;} }",
            "svc3/C.java": "package c;\nclass C {\n@org.apache.dubbo.config.annotation.DubboReference\nprivate OrderRpc orderRpc;\n}",
        })
        rpc = [e for e in g.edges if e["kind"] == "RPC"]
        self.assertEqual(len(rpc), 2, "双 provider 都要连边，不默取其一：%s" % [(e["src"], e["dst"]) for e in rpc])
        self.assertTrue(all(e["conf"] == "AMBIGUOUS" for e in rpc), "多 provider 必须显式 AMBIGUOUS")

    def test_matrix_doc_declares_every_construct(self):
        doc = open(os.path.join(ROOT, "docs", "capability-matrix.md"), encoding="utf-8").read()
        for item in ("Spring 路由", "MyBatis", "动态 SQL", "多 provider", "RocketMQ", "Kafka",
                     "JPA", "跨端", "重载", "字段别名", "匿名类"):
            self.assertIn(item, doc, "能力矩阵必须逐构造声明：%s" % item)
        self.assertIn("未知", doc, "矩阵必须显式列出未知项")

if __name__ == "__main__":
    unittest.main()
