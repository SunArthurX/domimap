"""HTML 摄入契约（product-html-ingestion）：去标签、实体解码、无文本层显式跳过、可检索。"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from domimap import lite_scan  # noqa: E402


def scan_tmp(files):
    base = tempfile.mkdtemp(prefix="dm-html-")
    for rel, content in files.items():
        path = os.path.join(base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(content)
    return lite_scan.scan_repo(base), base


HTML_FULL = """<html><head><title>订单透图</title><style>.x{color:red}</style>
<script>var config = '页面脚本不应入正文';</script></head>
<body><h1>商品中心</h1><p>透图规则：主图必须白底，&#20013;文标题不可遮挡。</p>
<a href="/next">下一页</a></body></html>"""


class TestHtmlIngestion(unittest.TestCase):
    def test_full_html_ingested_with_tags_stripped(self):
        R, _ = scan_tmp({"doc/page.html": HTML_FULL})
        self.assertEqual(len(R["docs"]), 1)
        text = R["docs"][0]["text"]
        self.assertIn("透图规则", text)
        self.assertIn("主图必须白底", text)
        self.assertIn("中文标题不可遮挡", text)  # &#20013; 数值实体已解码
        self.assertNotIn("<p>", text)
        self.assertNotIn("页面脚本不应入正文", text, "script 内容不得进入正文")
        self.assertNotIn("color:red", text, "style 内容不得进入正文")

    def test_empty_html_skipped_explicitly(self):
        R, _ = scan_tmp({"doc/empty.htm": "<html><head></head><body></body></html>",
                         "doc/only_script.html":
                             "<html><body><script>仅脚本</script></body></html>"})
        self.assertEqual(R["docs"], [])
        reasons = {s["file"]: s["reason"] for s in R["coverage"]["skipped"]}
        self.assertIn("HTML 无文本层", reasons.get("doc/empty.htm", ""))
        self.assertIn("HTML 无文本层", reasons.get("doc/only_script.html", ""))

    def test_named_entities_decoded(self):
        R, _ = scan_tmp({"doc/e.html": "<p>A &amp; B &lt;tag&gt; &quot;q&quot;</p>"})
        self.assertIn("A & B <tag> \"q\"", R["docs"][0]["text"])

    def test_html_searchable_via_graph(self):
        R, _ = scan_tmp({"doc/page.html": HTML_FULL})
        from domimap.graph import Graph, load_seeds
        from domimap.search import Searcher
        g = Graph()
        g.build_from_records(R, load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
        result = Searcher(g).query("透图 主图 白底", top_k=5)
        files = [n.get("file") for n in result.get("seeds", [])]
        self.assertTrue(any("page.html" in (f or "") for f in files),
                        "html 证据应可被检索命中: %s" % files)

    def test_existing_doc_behaviour_unchanged(self):
        R, _ = scan_tmp({"doc/note.md": "---\nvalid_until: 2030-01-01\n---\n正文说明"})
        doc = R["docs"][0]
        self.assertEqual(doc.get("valid_until"), "2030-01-01")


if __name__ == "__main__":
    unittest.main()
