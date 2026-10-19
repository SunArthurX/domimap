"""中英技术域词汇桥契约（product-en-bridge）。

公共语料评测实证：中文查询"接入 教程"无法命中英文 README——最大缺口（8 题）。
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from domimap.tokenize import tokenize, EN_BRIDGE  # noqa: E402


class TestEnBridgeTokenize(unittest.TestCase):
    def test_chinese_bigram_gets_english_synonyms(self):
        toks = tokenize("接入 教程")
        self.assertIn("接入", toks)
        self.assertIn("integrate", toks, "接入应桥到 integrate")
        self.assertIn("tutorial", toks, "教程应桥到 tutorial")

    def test_config_bridge(self):
        toks = tokenize("配置中心")
        self.assertIn("config", toks, "配置应桥到 config")

    def test_english_query_gets_chinese_context(self):
        # 英文 token 不变，但索引侧中文文档的"接入"gram 会附加 integrate → 双向可搜
        toks = tokenize("integrate tutorial")
        self.assertIn("integrate", toks)
        self.assertIn("tutorial", toks)

    def test_no_bridge_for_non_tech_words(self):
        toks = tokenize("红烧肉很好吃")
        self.assertNotIn("integrate", toks)

    def test_bridge_words_are_generic(self):
        """负例：桥词表不得含 benchmark 特定词（如具体仓库名/gold 路径片段）。"""
        banned = ["apijson", "nacos", "shardingsphere", "dubbo", "rocketmq",
                  "mall", "litemall", "eladmin", "vhr", "jeecg"]
        for cn, ens in EN_BRIDGE.items():
            if isinstance(ens, str):
                ens = [ens]
            for en in ens:
                for b in banned:
                    self.assertNotIn(b, en.lower(),
                                     "桥词含 benchmark 特定词 %s" % b)


class TestDocTypePrior(unittest.TestCase):
    def _build(self, files):
        base = tempfile.mkdtemp(prefix="dm-enbridge-")
        for rel, content in files.items():
            path = os.path.join(base, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w", encoding="utf-8").write(content)
        from domimap import lite_scan
        R = lite_scan.scan_repo(base)
        from domimap.graph import Graph, load_seeds
        from domimap.search import Searcher
        g = Graph()
        g.build_from_records(R, load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
        return Searcher(g)

    def test_readme_boosted_over_plain_doc(self):
        s = self._build({
            "README.md": "# Tutorial\nGetting started with integration guide.\n" + "detail\n" * 30,
            "doc/notes.txt": "Getting started with integration guide.\n" + "detail\n" * 30,
        })
        r = s.query("教程 入门", top_k=5)
        self.assertFalse(r.get("refused"))
        files = [n["file"] for n in r["seeds"]]
        self.assertEqual(files[0], "README.md",
                         "README/Tutorial 类文件应获先验加成排前: %s" % files)

    def test_code_node_not_affected_by_doc_prior(self):
        s = self._build({
            "README.md": "# readme\n" + "内容\n" * 30,
            "src/OrderService.java":
                "/**\n * 订单 改价 处理服务\n */\npublic class OrderService {\n}\n",
        })
        r = s.query("OrderService", top_k=5)
        self.assertFalse(r.get("refused"))
        self.assertEqual(r["seeds"][0]["kind"], "Class",
                         "代码节点不受文档类型先验影响")


if __name__ == "__main__":
    unittest.main()
