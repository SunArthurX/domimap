"""嵌入索引契约（product-embedding-index）。

核心语义：默认关；建库幂等（sha 键复用）；RRF 融合替换 scored 序（下游零变化）；
拒答守门先于融合（负例不因语义变命中）；索引/后端缺失优雅回退。全部 hermetic（假后端）。
"""
import math
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from domimap import embedding  # noqa: E402
from domimap import lite_scan  # noqa: E402
from domimap.graph import Graph, load_seeds  # noqa: E402
from domimap.search import Searcher  # noqa: E402

SEEDS = load_seeds(os.path.join(ROOT, "domimap", "seeds.json"))

FILES = {
    "docs/refund.md": "refund processing policy for returned orders and settlement",
    "docs/faq.md": "frequently asked questions about account setup alpha",
    "sql/schema.sql": "CREATE TABLE refund_record (order_id INT, amount DECIMAL);",
    "src/Alpha.java": "public class AlphaSvc { public String beta() { return \"x\"; } }\n",
}
# 中文查询与全部内容零词面交集（图无 CJK → 覆盖率门会拒答守门路径；换含拉丁词查询走主路径）
QUERY_CN = "退款 结算 处理 规则"
QUERY_HIT = "refund settlement policy"


def build_graph():
    ws = tempfile.mkdtemp(prefix="dm-emb-ws-")
    out = tempfile.mkdtemp(prefix="dm-emb-out-")
    for rel, text in FILES.items():
        path = os.path.join(ws, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    g = Graph()
    g.build_from_records(lite_scan.scan_repo(ws), SEEDS)
    graph_path = os.path.join(out, "graph.json")
    g.save(graph_path)
    return graph_path


class FakeBackend:
    """确定性假后端：按与目标文本的词面重叠构造 2 维语义向量。"""
    name = "fake:test"

    def __init__(self):
        self.query_calls = 0
        self.text_calls = 0
        self.seen_texts = []

    @staticmethod
    def _vec(text):
        t = text.lower()
        return [1.0 if "refund" in t or "退款" in t or "结算" in t else 0.0,
                1.0 if "faq" in t or "alpha" in t else 0.0]

    def embed_texts(self, texts):
        self.text_calls += len(texts)
        self.seen_texts.extend(texts)
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        self.query_calls += 1
        self.seen_texts.append("Q:" + text)
        return self._vec(text)


def _fake_factory():
    backend = FakeBackend()
    return (lambda: backend), backend


class TestEmbeddingIndex(unittest.TestCase):
    def setUp(self):
        embedding._QUERY_CACHE.clear()
        os.environ.pop(embedding.EMB_ENV, None)
        self.graph_path = build_graph()
        self.g = Graph.load(self.graph_path)
        self.searcher = Searcher(self.g)

    def tearDown(self):
        embedding._QUERY_CACHE.clear()
        os.environ.pop(embedding.EMB_ENV, None)

    def store(self):
        factory, backend = _fake_factory()
        store, stats = embedding.build_index(self.g, backend_factory=factory)
        return store, stats, backend

    def test_build_targets_and_truncation(self):
        store, stats, backend = self.store()
        kinds = {self.g.nodes[n]["kind"] for n in store["items"]}
        self.assertTrue(kinds <= {"Doc", "Knowledge", "SqlStmt", "Table"})
        self.assertGreater(stats["total"], 0)
        self.assertEqual(stats["embedded"], stats["total"])
        # SQL 文本截断到 400、文档到 2000
        long_doc = next((n for n in self.g.nodes.values()
                         if n["kind"] == "Doc" and len(n["meta"].get("text", "")) > 2000), None)
        if long_doc:
            seen = [t for t in backend.seen_texts if len(t) < len(long_doc["meta"]["text"])]
            self.assertTrue(seen)

    def test_build_idempotent_reuse(self):
        store1, _, backend = self.store()
        before = backend.text_calls
        store2, stats2 = embedding.build_index(self.g, backend_factory=lambda: backend,
                                               existing=store1)
        self.assertEqual(stats2["reused"], stats2["total"], "第二次全部复用")
        self.assertEqual(stats2["embedded"], 0)
        self.assertEqual(backend.text_calls, before, "幂等：不再调用后端")

    def test_fuse_rrf_semantic_first_can_lead(self):
        bm25 = [(3.0, "a"), (2.0, "b"), (1.0, "c")]
        sem = [(0.9, "z"), (0.8, "b")]
        fused = embedding.fuse_rrf(bm25, sem)
        order = [n for _, n in fused]
        # RRF 语义：双榜在列者（b）合计分最高居首；单榜榜首 a/z 同分次之；c 尾部
        self.assertEqual(order[0], "b")
        self.assertEqual(sorted(order[1:3]), ["a", "z"])
        self.assertEqual(order[3], "c")
        self.assertEqual(fused[1][0], fused[2][0])

    def test_query_embed_semantic_only_node_surfaces(self):
        store, _, backend = self.store()
        self.searcher.emb_store = store
        self.searcher.set_embedding_backend(lambda: backend)
        r = self.searcher.query(QUERY_HIT, top_k=6, embed=True)
        self.assertFalse(r["refused"])
        self.assertIsNotNone(r["embedding"])
        files = [n["file"] for n in r["seeds"]]
        self.assertTrue(any("refund" in f or "schema" in f for f in files),
                        "语义相关节点应 surfaced: %s" % files)

    def test_default_off_no_semantic(self):
        store, _, backend = self.store()
        self.searcher.emb_store = store
        self.searcher.set_embedding_backend(lambda: backend)
        r = self.searcher.query(QUERY_HIT, top_k=6)
        self.assertIsNone(r.get("embedding"))
        self.assertEqual(backend.query_calls, 0)

    def test_missing_store_graceful(self):
        r = self.searcher.query(QUERY_HIT, top_k=6, embed=True)
        self.assertFalse(r["refused"])
        self.assertIsNone(r.get("embedding"))

    def test_backend_unavailable_graceful(self):
        store, _, _ = self.store()
        self.searcher.emb_store = store

        def boom():
            raise embedding.EmbeddingUnavailable("fastembed missing")

        original = embedding.make_backend
        embedding.make_backend = boom
        try:
            r = self.searcher.query(QUERY_HIT, top_k=6, embed=True)
        finally:
            embedding.make_backend = original
        self.assertFalse(r["refused"])
        self.assertIsNone(r["embedding"], "后端缺失 → BM25 原序继续")

    def test_refusal_gate_precedes_fusion(self):
        """拒答守门先于语义融合：图外概念查询不因嵌入变假命中（负例底线）。"""
        store, _, backend = self.store()
        self.searcher.emb_store = store
        self.searcher.set_embedding_backend(lambda: backend)
        r = self.searcher.query("zzz_totally_absent_concept", top_k=6, embed=True)
        self.assertTrue(r["refused"], "标识符缺席守门必须先拒")
        self.assertEqual(backend.query_calls, 0, "拒答路径不触语义召回")

    def test_store_roundtrip(self):
        store, _, _ = self.store()
        path = os.path.join(tempfile.mkdtemp(), "g.emb.json")
        embedding.save_store(store, path)
        loaded = embedding.load_store(path)
        self.assertEqual(loaded["schema"], embedding.EMB_SCHEMA)
        self.assertEqual(len(loaded["items"]), len(store["items"]))
        corrupt = os.path.join(tempfile.mkdtemp(), "bad.emb.json")
        with open(corrupt, "w") as f:
            f.write("{not json")
        self.assertIsNone(embedding.load_store(corrupt))

    def test_local_backend_query_prefix(self):
        """bge 查询指令前缀：本地后端 embed_query 的输入带前缀（跨语言分离度）。"""

        class SpyModel:
            def __init__(self):
                self.captured = None

            def embed(self, texts):
                self.captured = texts
                yield [0.1, 0.2]

        spy = object.__new__(embedding.LocalFastembedBackend)
        spy._model = SpyModel()
        vec = spy.embed_query("退款 规则")
        self.assertEqual(vec, [0.1, 0.2])
        self.assertTrue(spy._model.captured[0].startswith(embedding.BGE_QUERY_PREFIX))

    def test_code_intent_gate_skips_fusion(self):
        """代码定位意图（处理类/位置/表/定义…）→ 词法通道权威，跳过语义融合（pub A/B
        实测 RRF 稀释词法精确证据致 code_location 19/27→8/27 回归的守卫）。"""
        store, _, backend = self.store()
        self.searcher.emb_store = store
        self.searcher.set_embedding_backend(lambda: backend)
        r = self.searcher.query("refund 位置", top_k=6, embed=True)
        self.assertEqual(backend.query_calls, 0, "代码意图查询不触语义召回")
        self.assertEqual(r["embedding"].get("skipped"), "code_intent")

    def test_doc_intent_fuses(self):
        store, _, backend = self.store()
        self.searcher.emb_store = store
        self.searcher.set_embedding_backend(lambda: backend)
        r = self.searcher.query(QUERY_HIT, top_k=6, embed=True)
        self.assertEqual(backend.query_calls, 1)
        self.assertIsNone(r["embedding"].get("skipped"))


if __name__ == "__main__":
    unittest.main()
