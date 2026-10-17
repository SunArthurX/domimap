"""标识符精确匹配加权 + 单字噪声抑制契约（product-identifier-ranking）。

数值定位（干净批图实测）：tbl:OP_OPERATOR 仅凭 op_operator 0.53 分，被只匹配
['服务','务','服'] 的 SaleServiceDTO（1.29）压出 top50。
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from domimap import lite_scan  # noqa: E402

MAPPER = ("<mapper namespace=\"x\"><select id=\"q\">"
          "SELECT * FROM t_op_operator WHERE 1=1</select></mapper>\n")
NOISE_JAVA = ("public class SaleServiceDTO {\n"
              "// 服务 服务 服务 服务 通用说明 读写 读写\n" * 3 + "}\n")


def build(files):
    base = tempfile.mkdtemp(prefix="dm-idr-")
    for rel, content in files.items():
        path = os.path.join(base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write(content)
    R = lite_scan.scan_repo(base)
    from domimap.graph import Graph, load_seeds
    from domimap.search import Searcher
    g = Graph()
    g.build_from_records(R, load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
    return Searcher(g)


class TestIdentifierRanking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = build({"sqlmap/OpMapper.xml": MAPPER,
                       "src/com/example/gx/dto/SaleServiceDTO.java": NOISE_JAVA})

    def test_identifier_named_node_outranks_generic_pileup(self):
        r = self.s.query("t_op_operator 表 哪些服务 读写 跨服务", top_k=5)
        self.assertFalse(r.get("refused"))
        names = [n["name"] for n in r["seeds"]]
        self.assertEqual(names[0], "t_op_operator",
                         "名称精确匹配的表节点应居首: %s" % names)
        if "SaleServiceDTO" in names:
            self.assertLess(names.index("t_op_operator"),
                            names.index("SaleServiceDTO"))

    def test_boost_only_on_exact_name(self):
        # 近名：t_op_operatorr 不等于任何 name → 无 boost；仍按常规词法
        r = self.s.query("t_op_operatorr 表 定义", top_k=5)
        names = [n["name"] for n in r.get("seeds", [])]
        self.assertNotIn("t_op_operator", names[:1] if r.get("refused") else names,
                         "近名不得因 boost 获得首位")

    def test_single_cjk_chars_do_not_score(self):
        # 只有单字与噪声词的节点不应凭计数得分：查询命中应为表节点或拒答
        r = self.s.query("t_op_operator 服 务", top_k=5)
        self.assertFalse(r.get("refused"))
        self.assertEqual(r["seeds"][0]["name"], "t_op_operator")

    def test_chinese_query_semantics_unchanged(self):
        s2 = build({"doc/note.md": "# 说明\n运费模板计费规则按重量计费。" + "补充细节。\n" * 30})
        r = s2.query("运费模板 计费规则", top_k=5)
        self.assertFalse(r.get("refused"))
        self.assertEqual(r["seeds"][0]["file"], "doc/note.md")


if __name__ == "__main__":
    unittest.main()
