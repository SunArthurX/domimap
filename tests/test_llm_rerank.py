"""查询期 LLM 语义重排契约（product-llm-rerank）。

核心语义：默认关；重排对象=选择融合之前的原始 scored 序；LLM 只排列给定不透明 id
（未知 id 丢弃/缺席补尾/失败原序）；下游三路融合与保底语义零变化；缓存去重。
全部 hermetic（假客户端，无网络）。
"""
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from domimap import lite_scan  # noqa: E402
from domimap import llm_rerank  # noqa: E402
from domimap.graph import Graph, load_seeds  # noqa: E402
from domimap.search import Searcher  # noqa: E402

SEEDS = load_seeds(os.path.join(ROOT, "domimap", "seeds.json"))

FILES = {
    "docs/g1.md": "alpha beta gamma delta epsilon zeta theta",
    "docs/g2.md": "alpha beta gamma delta",
    "docs/g3.md": "alpha beta",
    "sql/schema.sql": "CREATE TABLE alpha_tbl (beta_id INT); INSERT INTO alpha_tbl ...",
    "src/A.java": "package com.example.a;\n\n/** alpha beta */\n"
                  "public class AlphaSvc { public String gamma() { return \"x\"; } }\n",
    "src/B.java": "package com.example.b;\n\n/** alpha */\n"
                  "public class BetaSvc { public String delta() { return \"y\"; } }\n",
    "src/C.java": "package com.example.c;\n\npublic class GammaSvc { public int beta() { return 1; } }\n",
}
QUERY = "alpha beta gamma"


def build_graph():
    ws = tempfile.mkdtemp(prefix="dm-rr-ws-")
    out = tempfile.mkdtemp(prefix="dm-rr-out-")
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


class FakeClient:
    def __init__(self, payload=None, error=None):
        self.calls = 0
        self.payload = payload
        self.error = error
        self.last_user = ""

    def complete(self, system, user):
        self.calls += 1
        self.last_user = user
        if self.error:
            raise self.error
        return self.payload, {}


def fake_factory(payload=None, error=None):
    client = FakeClient(payload, error)
    return lambda: client, client


class TestLlmRerank(unittest.TestCase):
    def setUp(self):
        llm_rerank._CACHE.clear()
        os.environ.pop(llm_rerank.RERANK_ENV, None)
        self._orig_client = llm_rerank._client
        self.graph_path = build_graph()
        self.searcher = Searcher(Graph.load(self.graph_path))
        self.baseline = [n["file"] for n in
                         self.searcher.query(QUERY, top_k=6)["seeds"]]

    def tearDown(self):
        llm_rerank._CACHE.clear()
        os.environ.pop(llm_rerank.RERANK_ENV, None)
        llm_rerank._client = self._orig_client

    def test_default_off_no_call(self):
        real = llm_rerank.rerank
        llm_rerank.rerank = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("default off must not rerank"))
        try:
            r = self.searcher.query(QUERY, top_k=6)
        finally:
            llm_rerank.rerank = real
        self.assertFalse(r["refused"])
        self.assertIsNone(r["llm_rerank"])

    def test_enabled_reorders_results(self):
        factory, client = fake_factory('{"ranking": ["c9", "c8", "c7"]}')
        llm_rerank._client = factory
        r = self.searcher.query(QUERY, top_k=6, rerank=True)
        self.assertEqual(client.calls, 1)
        self.assertIsNotNone(r["llm_rerank"])
        self.assertEqual(r["llm_rerank"]["pool"],
                         client.last_user.count("| bm25="), "池大小=送入候选数")
        files = [n["file"] for n in r["seeds"]]
        self.assertNotEqual(files, self.baseline, "重排应改变顺序")

    def test_unknown_and_duplicate_ids_ignored(self):
        factory, client = fake_factory(
            '{"ranking": ["c999", "c0", "c0", "c1"]}')
        llm_rerank._client = factory
        r = self.searcher.query(QUERY, top_k=6, rerank=True)
        self.assertEqual(client.calls, 1)
        files = [n["file"] for n in r["seeds"]]
        self.assertEqual(files[0], self.baseline[0], "未知 id 丢弃后 c0（BM25 首名）居首")

    def test_incomplete_ranking_appends_bm25_order(self):
        factory, client = fake_factory('{"ranking": ["c5", "c4"]}')
        llm_rerank._client = factory
        r = self.searcher.query(QUERY, top_k=6, rerank=True)
        self.assertIn("部分排列", r["llm_rerank"]["note"])
        files = [n["file"] for n in r["seeds"]]
        # 下游融合会重排位置，但重排头部（BM25 第 6/5 名）必须进入最终成员
        self.assertIn(self.baseline[5], files, "c5（BM25 第 6 名）应进入结果")
        self.assertIn(self.baseline[4], files, "c4（BM25 第 5 名）应进入结果")

    def test_parse_failure_keeps_order(self):
        factory, client = fake_factory("模型自由发挥非 JSON")
        llm_rerank._client = factory
        r = self.searcher.query(QUERY, top_k=6, rerank=True)
        files = [n["file"] for n in r["seeds"]]
        self.assertEqual(files, self.baseline)
        self.assertIsNone(r["llm_rerank"])

    def test_client_error_graceful(self):
        factory, client = fake_factory(error=RuntimeError("down"))
        llm_rerank._client = factory
        r = self.searcher.query(QUERY, top_k=6, rerank=True)
        self.assertFalse(r["refused"])
        self.assertEqual([n["file"] for n in r["seeds"]], self.baseline)

    def test_cache_prevents_second_call(self):
        factory, client = fake_factory('{"ranking": ["c3", "c2", "c1"]}')
        llm_rerank._client = factory
        r1 = self.searcher.query(QUERY, top_k=6, rerank=True)
        r2 = Searcher(Graph.load(self.graph_path)).query(QUERY, top_k=6, rerank=True)
        self.assertEqual(client.calls, 1)
        self.assertEqual([n["file"] for n in r1["seeds"]],
                         [n["file"] for n in r2["seeds"]])

    def test_pool_limit_respected(self):
        factory, client = fake_factory('{"ranking": ["c2", "c1", "c0"]}')
        llm_rerank._client = factory
        self.searcher.query(QUERY, top_k=6, rerank=True, rerank_pool=3)
        self.assertEqual(client.last_user.count("| bm25="), 3, "只应送 3 个候选")

    def test_small_result_no_call(self):
        factory, client = fake_factory('{"ranking": ["c1"]}')
        llm_rerank._client = factory
        r = self.searcher.query("zeta theta", top_k=6, rerank=True)
        self.assertLessEqual(len(r["seeds"]), 6)
        self.assertEqual(client.calls, 0, "候选数 ≤ top_k 不调用重排")

    def test_floor_survives_rerank(self):
        """重排不得使非空路失去代表：文档/代码两路在场时最终结果两路都有。"""
        factory, _client = fake_factory('{"ranking": ["c9", "c8", "c7", "c6", "c5", "c4"]}')
        llm_rerank._client = factory
        r = self.searcher.query(QUERY, top_k=6, rerank=True)
        kinds = {n["kind"] for n in r["seeds"]}
        self.assertTrue(any(k in kinds for k in ("Doc", "Knowledge")), "文档路保底：{}".format(kinds))
        self.assertTrue(any(k not in ("Doc", "Knowledge") for k in kinds), "代码路保底：{}".format(kinds))

    def test_cli_flag_wired(self):
        env = dict(os.environ)
        env.pop(llm_rerank.RERANK_ENV, None)
        p = subprocess.run(
            [sys.executable, "-B", "-m", "domimap", "query",
             "alpha beta", "-g", self.graph_path, "--rerank", "--rerank-pool", "8"],
            capture_output=True, text=True, cwd=ROOT, env=env, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)


if __name__ == "__main__":
    unittest.main()
