"""`domimap schema` 契约（R11/AC-R11-01）：机器可读图谱 schema 与实现零漂移。

schema.json 是对外承诺（AI 客户端按它消费图），因此用真实构建的夹具图
反向校验：图中出现的一切节点/边/置信度/prov 域必须已被 schema 声明；
MCP 工具清单必须与 mcp.TOOLS 一致。
"""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from domimap import lite_scan  # noqa: E402
from domimap.graph import Graph, load_seeds  # noqa: E402


def load_schema():
    with open(os.path.join(ROOT, "domimap", "schema.json"), encoding="utf-8") as f:
        return json.load(f)


def built_graph():
    R = lite_scan.scan_repo(os.path.join(HERE, "fixtures", "mini"), repo_label="mini")
    g = Graph()
    g.build_from_records(R, load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
    return g


class TestSchemaContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load_schema()
        cls.graph = built_graph()

    def test_required_sections(self):
        for key in ("node_kinds", "edge_kinds", "confidence_levels",
                    "provenance_domains", "mcp_tools", "refusal_gates", "evidence"):
            self.assertIn(key, self.schema)

    def test_every_actual_kind_is_declared(self):
        node_kinds = {n["kind"] for n in self.graph.nodes.values()}
        edge_kinds = {e["kind"] for e in self.graph.edges}
        self.assertTrue(node_kinds, "夹具图非空")
        self.assertFalse(node_kinds - set(self.schema["node_kinds"]),
                         "未声明的节点 kind: %s" % (node_kinds - set(self.schema["node_kinds"])))
        self.assertFalse(edge_kinds - set(self.schema["edge_kinds"]),
                         "未声明的边 kind: %s" % (edge_kinds - set(self.schema["edge_kinds"])))

    def test_confidence_and_prov_domains_covered(self):
        confs = {n.get("conf") for n in self.graph.nodes.values()} | \
                {e.get("conf") for e in self.graph.edges}
        declared = set(self.schema["confidence_levels"]) | set(self.schema["confidence_semantics_zh"])
        self.assertFalse(confs - declared, "未声明的置信度: %s" % (confs - declared))
        provs = {str(p).split(":", 1)[0] for p in
                 ([n.get("prov") for n in self.graph.nodes.values()] +
                  [e.get("prov") for e in self.graph.edges]) if p}
        self.assertFalse(provs - set(self.schema["provenance_domains"]),
                         "未声明的 prov 域: %s" % (provs - set(self.schema["provenance_domains"])))

    def test_mcp_tools_match_server_registry(self):
        from domimap.mcp import TOOLS
        self.assertEqual(self.schema["mcp_tools"], [t["name"] for t in TOOLS])

    def test_cli_outputs_valid_json(self):
        p = subprocess.run([sys.executable, "-B", "-m", "domimap", "schema"],
                           cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        d = json.loads(p.stdout)
        self.assertEqual(d["name"], self.schema["name"])

    def test_node_id_prefixes_match(self):
        for n in self.graph.nodes.values():
            prefix = self.schema["node_kinds"][n["kind"]]["id_prefix"]
            if prefix:
                self.assertTrue(n["id"].startswith(prefix),
                                "%s 应以 %s 开头: %s" % (n["kind"], prefix, n["id"]))


if __name__ == "__main__":
    unittest.main()
