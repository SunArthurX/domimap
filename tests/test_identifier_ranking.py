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


class TestBoostScopeOriginalOnly(unittest.TestCase):
    """retrieval-identifier-boost-scope：加成只属于原始查询标识符。

    seeds 域扩展词与类名撞名（商品→Item）不构成用户表达的"定义性同一"，不得以 ×3
    加成计分（真实语料实证：含"审核"实词的 docx 曾被 generic Item/Product 类压到
    第 15 名，修复后回到 top_k——真实语料回放见 out/dev-ws 与 AC-R15-04 证据；
    此处钉住机制语义与端到端不回归）。
    """

    @classmethod
    def setUpClass(cls):
        cls.s = build({
            "src/com/example/Item.java": "public class Item {\n"
                                         "// 无关 generic 类，仅靠类名撞扩展词\n}\n",
            "doc/audit.md": "# 商品审核说明\n商品 审核状态 流转 规则：状态机与回退。\n"
                            + "细节补充。\n" * 20,
        })
        cls.item_nid = next(nid for nid, n in cls.s.g.nodes.items()
                            if n["name"] == "Item")

    def test_boost_only_when_identifier_in_original_tokens(self):
        # 机制：加成仅当 name_tokens（原始查询）含与节点名全等的 token；比率恰为 ×3
        boosted = self.s._score(["item"], self.item_nid, name_tokens=["item"])
        unboosted = self.s._score(["item"], self.item_nid, name_tokens=["商品", "审核"])
        self.assertGreater(boosted, 0)
        self.assertAlmostEqual(boosted, unboosted * 3.0, places=6,
                               msg="名称精确加成应为恰好 ×3")
        legacy = self.s._score(["item"], self.item_nid)  # 兼容旧调用：默认全量 qtokens
        self.assertAlmostEqual(legacy, boosted, places=6)

    def test_expansion_token_weight_ratio(self):
        # 机制：扩展词（weak_tokens）按 EXPANSION_TOKEN_WEIGHT 计权；原始词全权
        from domimap.search import EXPANSION_TOKEN_WEIGHT
        full = self.s._score(["item"], self.item_nid, name_tokens=["商品"])
        weak = self.s._score(["item"], self.item_nid, name_tokens=["商品"],
                             weak_tokens={"item"})
        self.assertGreater(full, 0)
        self.assertAlmostEqual(weak, full * EXPANSION_TOKEN_WEIGHT, places=6,
                               msg="扩展词计分应按 EXPANSION_TOKEN_WEIGHT 降权")
        # 原始查询也含该词时不得降权（weak 集构造排除原始词）
        self.assertAlmostEqual(
            self.s._score(["item"], self.item_nid, name_tokens=["item"],
                          weak_tokens=set()),
            self.s._score(["item"], self.item_nid, name_tokens=["item"],
                          weak_tokens=None), places=6)

    def test_seeds_expansion_collision_query_doc_first(self):
        r = self.s.query("商品 审核状态 流转", top_k=5)
        self.assertFalse(r.get("refused"))
        self.assertEqual(r["seeds"][0]["file"], "doc/audit.md",
                         "含原始实词的文档应居首（不得被撞名类凭扩展词霸榜）")

    def test_original_identifier_boost_kept(self):
        s2 = build({"src/com/example/StockClient.java":
                    "public class StockClient {\n// 库存 客户端 说明\n}\n",
                    "doc/other.md": "# 其它\n库存 其它 内容 说明。\n" + "细节。\n" * 30})
        # 原始查询自带标识符：加成保留（与既有契约一致）
        r = s2.query("StockClient 库存", top_k=5)
        self.assertFalse(r.get("refused"))
        self.assertEqual(r["seeds"][0]["name"], "StockClient")


if __name__ == "__main__":
    unittest.main()
