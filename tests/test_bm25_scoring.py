"""BM25 长度归一契约（product-bm25-scoring）。

诊断实证：dv2-0060 的 Jhub 指南（50KB docx）排第 49，top5 全为短注释 Dao 类——
线性 tf/total 使 1/20 碾压 1/20000。
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from domimap import lite_scan  # noqa: E402


def build(files):
    base = tempfile.mkdtemp(prefix="dm-bm25-")
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


class TestBM25Scoring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        long_doc = ("# 测试环境 开发者指南\n\n接口描述方式说明如下。\n"
                    + "测试环境 接口 描述 方式 说明 内容段落。\n" * 120)
        short_comment_dao = ("/**\n * 测试环境\n */\n"
                             "public interface VenderStoresDao {\n}\n")
        cls.s = build({"doc/guide.md": long_doc,
                       "src/VenderStoresDao.java": short_comment_dao})

    def test_long_doc_beats_short_comment_node(self):
        r = self.s.query("测试环境 开发者指南 接口 描述 方式 说明", top_k=5)
        self.assertFalse(r.get("refused"))
        files = [n["file"] for n in r["seeds"]]
        self.assertIn("doc/guide.md", files[:2],
                      "命中全部查询词的长文档应进入前列（保底席语义：席位保证）: %s" % files)
        self.assertIn("doc/guide.md", files)

    def test_short_node_saturation_no_free_domination(self):
        # 只含一个查询词的短节点不得凭"短"霸榜
        r = self.s.query("开发者指南", top_k=5)
        self.assertFalse(r.get("refused"))
        self.assertIn("doc/guide.md", [n["file"] for n in r["seeds"][:2]])

    def test_identifier_query_still_exact(self):
        s2 = build({"sqlmap/A.xml":
                    "<mapper><select>SELECT * FROM t_area WHERE 1=1</select></mapper>",
                    "src/Other.java": "public class Other {\n}\n"})
        r = s2.query("t_area 表 定义", top_k=3)
        self.assertFalse(r.get("refused"))
        self.assertEqual(r["seeds"][0]["name"], "t_area")


if __name__ == "__main__":
    unittest.main()
