"""中英技术域词汇桥契约（product-en-bridge，v2：查询回退桥）。

架构修正：桥接不进主计分路径（tokenize 层桥曾稀释 BM25 IDF 致 11 题回退），
只在覆盖率不足时作为查询回退扩展。
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from domimap.tokenize import EN_BRIDGE  # noqa: E402


def _build(files):
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


class TestEnBridgeFallback(unittest.TestCase):
    def test_cn_query_finds_en_readme_via_bridge(self):
        """中文查询"接入 教程"通过回退桥找到英文 README。"""
        s = _build({"README.md":
                    "# Getting Started Tutorial\nIntegration guide for API.\n" + "Detail content here.\n" * 30})
        r = s.query("接入 教程", top_k=5)
        # 不应拒答（桥接回退生效）
        self.assertFalse(r.get("refused"),
                         "中文查询应通过回退桥命中英文 README: %s" % r.get("text", "")[:80])
        files = [n["file"] for n in r.get("seeds", [])]
        self.assertTrue(any("README" in f for f in files),
                        "README 应在结果中: %s" % files)

    def test_cn_query_with_cn_content_not_affected(self):
        """中文索引内容存在时，主路径不受桥接干扰（精确匹配优先）。"""
        s = _build({"doc/说明.md": "# 订单改价\n改价必须审核。\n" + "细节。\n" * 30,
                    "README.md": "# Getting Started\nIntegration guide.\n" + "Detail.\n" * 30})
        r = s.query("订单改价 审核", top_k=5)
        self.assertFalse(r.get("refused"))
        self.assertEqual(r["seeds"][0]["file"], "doc/说明.md",
                         "中文内容主路径匹配应不受桥影响")

    def test_bridge_words_generic(self):
        """负例：桥词表不得含 benchmark 特定词。"""
        banned = ["apijson", "nacos", "shardingsphere", "dubbo", "rocketmq",
                  "mall", "litemall", "eladmin", "vhr", "jeecg"]
        for cn, ens in EN_BRIDGE.items():
            if isinstance(ens, str):
                ens = [ens]
            for en in ens:
                for b in banned:
                    self.assertNotIn(b, en.lower())

    def test_doc_type_prior_readme_boosted(self):
        s = _build({"README.md": "# Tutorial\nGetting started guide.\n" + "detail\n" * 30,
                    "doc/notes.txt": "Getting started guide.\n" + "detail\n" * 30})
        r = s.query("getting started tutorial guide", top_k=5)
        self.assertFalse(r.get("refused"))
        files = [n["file"] for n in r["seeds"]]
        self.assertEqual(files[0], "README.md",
                         "README/Tutorial 类文件应获先验排前: %s" % files)

    def test_code_node_not_affected_by_doc_prior(self):
        s = _build({"README.md": "# readme\n" + "内容\n" * 30,
                    "src/OrderService.java":
                        "/**\n * 订单 改价 处理服务\n */\npublic class OrderService {\n}\n"})
        r = s.query("OrderService", top_k=5)
        self.assertFalse(r.get("refused"))
        self.assertEqual(r["seeds"][0]["kind"], "Class")


if __name__ == "__main__":
    unittest.main()
