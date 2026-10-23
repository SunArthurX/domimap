"""索引层长文档分段契约（product-doc-chunking）。

核心语义：>3500 字符的 Doc 分段（≤1500/重叠 250，换行边界优先）；chunk 的 file/kind
与原文档一致（路径级命中不变）；短文档零变化；索引/嵌入双端一致展开。
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from domimap import lite_scan  # noqa: E402
from domimap.chunking import CHUNK_SIZE, expand_node, split_chunks  # noqa: E402
from domimap.graph import Graph, load_seeds  # noqa: E402
from domimap.search import Searcher  # noqa: E402

SEEDS = load_seeds(os.path.join(ROOT, "domimap", "seeds.json"))

LONG_TAIL = "\n\n第40节 唯一尾锚词 犬羚兽 专属说明：仅本节出现。\n" + "填充行。 " * 200
LONG_DOC = "# 使用指南\n" + "常用词 通用说明 限制 条件。\n" * 300 + LONG_TAIL  # >3500 且锚词在后段
SHORT_DOC = "# 附录\n\n短文档 限制 条件。"

FILES = {"docs/long.md": LONG_DOC, "docs/short.md": SHORT_DOC}


def build_graph():
    ws = tempfile.mkdtemp(prefix="dm-chunk-ws-")
    for rel, text in FILES.items():
        p = os.path.join(ws, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    g = Graph()
    g.build_from_records(lite_scan.scan_repo(ws), SEEDS)
    return g


class TestSplitChunks(unittest.TestCase):
    def test_short_text_unchanged(self):
        self.assertEqual(split_chunks("短文本"), ["短文本"])
        self.assertEqual(split_chunks(""), [])

    def test_long_text_chunked_with_overlap(self):
        text = "\n".join("第%d行 内容词组填充" % i for i in range(400))  # ~6k chars
        chunks = split_chunks(text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= CHUNK_SIZE * 1.5 for c in chunks))
        joined = "\n".join(chunks)
        for i in (0, 100, 399):
            self.assertIn("第%d行" % i, joined, "分段不得丢内容")

    def test_hard_split_no_newlines(self):
        chunks = split_chunks("锚" * 6000)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= CHUNK_SIZE * 1.5 for c in chunks))


class TestExpandNode(unittest.TestCase):
    def setUp(self):
        self.g = build_graph()
        self.long_nid = next(n for n in self.g.nodes
                             if self.g.nodes[n].get("kind") == "Doc"
                             and len((self.g.nodes[n].get("meta") or {}).get("text") or "") > 3500)

    def test_long_doc_expands_short_returns_none(self):
        n = self.g.nodes[self.long_nid]
        expanded = expand_node(self.long_nid, n)
        self.assertGreater(len(expanded), 1)
        self.assertTrue(all(cid.startswith(self.long_nid + "#c") for cid, _ in expanded))
        files = {cn["file"] for _, cn in expanded}
        self.assertEqual(files, {n["file"]}, "chunk 的 file 必须与原文档一致")
        self.assertEqual({cn["kind"] for _, cn in expanded}, {"Doc"})
        # 尾段必须含后段锚词（嵌入/检索可见后段内容的契约）
        tail_texts = [cn["meta"]["text"] for _, cn in expanded]
        self.assertTrue(any("犬羚兽" in t for t in tail_texts), "后段锚词必须进入某分段")

        short_nid = next(n2 for n2 in self.g.nodes
                         if self.g.nodes[n2].get("kind") == "Doc" and n2 != self.long_nid)
        self.assertEqual(expand_node(short_nid, self.g.nodes[short_nid]),
                         [(short_nid, None)], "短文档不分段")


class TestSearcherChunking(unittest.TestCase):
    def test_tail_content_retrievable(self):
        """分段后，仅存在于长文后段的锚词可被检索命中（原整节点同样含该词，但段节点
        使命中更稳）。契约重点：chunk 命中渲染不炸（_node 回退 extra）。"""
        g = build_graph()
        s = Searcher(g)
        r = s.query("犬羚兽 专属说明", top_k=5)
        self.assertFalse(r.get("refused"), "尾段锚词必须可命中：%s" % r.get("text", "")[:80])
        files = [n["file"] for n in r["seeds"]]
        self.assertTrue(any("long.md" in f for f in files), files)

    def test_short_docs_unaffected(self):
        g = build_graph()
        s = Searcher(g)
        r = s.query("短文档 限制 条件", top_k=5)
        self.assertFalse(r.get("refused"))
        self.assertTrue(any("short.md" in n["file"] for n in r["seeds"]))


if __name__ == "__main__":
    unittest.main()
