"""查询期 LLM 语义桥契约（product-semantic-bridge）。

核心语义：默认关、只在"即将拒答"路径触发、LLM 词 df 接地、失败/未配置/解析失败
一律跳过（拒答文案逐字不变）、已命中查询零变化。全部 hermetic（假客户端，无网络）。
"""
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from domimap import lite_scan  # noqa: E402
from domimap import semantic_bridge  # noqa: E402
from domimap.graph import Graph, load_seeds  # noqa: E402
from domimap.search import Searcher  # noqa: E402

SEEDS = load_seeds(os.path.join(ROOT, "domimap", "seeds.json"))

FILES = {
    "docs/recon.md": "# Reconciliation Guide\n\nwriteoff settlement policy "
                     "for reconciliation differences between ledger entries",
    "src/Settlement.java": "package com.example.pay;\n\npublic class SettlementDao {\n"
                           "    public String reconDiff() { return \"writeoff\"; }\n}\n",
    "docs/cn.md": "对账说明",  # 图内出现 CJK → 中文单元计入覆盖率分母
}
# 中文查询与全部内容零词面交集，且不在静态 EN_BRIDGE 词典（对账/核销/差异 均缺席）
CN_QUERY = "对账 差异 自动核销"
REFUSE_MARK = "诚实拒答"


def build_graph():
    ws = tempfile.mkdtemp(prefix="dm-sb-ws-")
    out = tempfile.mkdtemp(prefix="dm-sb-out-")
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

    def complete(self, system, user):
        self.calls += 1
        if self.error:
            raise self.error
        return self.payload, {}


def fake_factory(payload=None, error=None):
    client = FakeClient(payload, error)
    return lambda: client, client


class TestSemanticBridge(unittest.TestCase):
    def setUp(self):
        semantic_bridge._CACHE.clear()
        os.environ.pop(semantic_bridge.BRIDGE_ENV, None)
        self._orig_client = semantic_bridge._client
        self.graph_path = build_graph()
        self.searcher = Searcher(Graph.load(self.graph_path))

    def tearDown(self):
        semantic_bridge._CACHE.clear()
        os.environ.pop(semantic_bridge.BRIDGE_ENV, None)
        semantic_bridge._client = self._orig_client

    def test_default_off_refusal_unchanged(self):
        """默认关：低覆盖查询按现状拒答，语义层零调用。"""
        real = semantic_bridge.expand_tokens
        semantic_bridge.expand_tokens = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("default off must not call bridge"))
        try:
            r = self.searcher.query(CN_QUERY, top_k=6)
        finally:
            semantic_bridge.expand_tokens = real
        self.assertTrue(r["refused"])
        self.assertIn(REFUSE_MARK, r["text"])

    def test_enabled_expansion_hits(self):
        """启用 + 模型词接地命中：拒答变正常返回，标注扩展词。"""
        factory, client = fake_factory(
            '{"terms": ["reconciliation", "writeoff", "settlement", "unicorn_term"]}')
        semantic_bridge._client = factory
        r = self.searcher.query(CN_QUERY, top_k=6, semantic=True)
        self.assertEqual(client.calls, 1)
        self.assertFalse(r["refused"], "接地词应命中：%s" % r["text"])
        info = r["semantic_bridge"]
        self.assertIn("reconciliation", info["tokens"])
        self.assertNotIn("unicorn_term", info["tokens"], "未接地词必须被过滤")
        self.assertIn("语义桥扩展", r["text"])

    def test_explicit_none_follows_env(self):
        """semantic=None 看 DOMIMAP_SEMANTIC_BRIDGE。"""
        os.environ[semantic_bridge.BRIDGE_ENV] = "1"
        factory, client = fake_factory(
            '{"terms": ["reconciliation", "writeoff", "settlement", "policy"]}')
        semantic_bridge._client = factory
        r = self.searcher.query(CN_QUERY, top_k=6)
        self.assertEqual(client.calls, 1)
        self.assertFalse(r["refused"])

    def test_grounding_empty_stays_refused(self):
        """模型词全部不在索引 → 拒答文案逐字不变。"""
        factory, client = fake_factory('{"terms": ["zzz_nothing", "qqq_gone"]}')
        semantic_bridge._client = factory
        r = self.searcher.query(CN_QUERY, top_k=6, semantic=True)
        self.assertTrue(r["refused"])
        self.assertIn(REFUSE_MARK, r["text"])
        self.assertEqual(client.calls, 1)

    def test_client_error_skips_gracefully(self):
        factory, client = fake_factory(error=RuntimeError("transport down"))
        semantic_bridge._client = factory
        r = self.searcher.query(CN_QUERY, top_k=6, semantic=True)
        self.assertTrue(r["refused"])
        self.assertEqual(client.calls, 1)

    def test_junk_response_skips(self):
        factory, client = fake_factory("这不是 JSON（模型自由发挥）")
        semantic_bridge._client = factory
        r = self.searcher.query(CN_QUERY, top_k=6, semantic=True)
        self.assertTrue(r["refused"])
        self.assertEqual(client.calls, 1)

    def test_cache_prevents_second_call(self):
        factory, client = fake_factory(
            '{"terms": ["reconciliation", "writeoff", "settlement", "policy"]}')
        semantic_bridge._client = factory
        r1 = self.searcher.query(CN_QUERY, top_k=6, semantic=True)
        r2 = Searcher(Graph.load(self.graph_path)).query(CN_QUERY, top_k=6, semantic=True)
        self.assertEqual(client.calls, 1, "同查询第二次必须命中缓存")
        self.assertFalse(r1["refused"])
        self.assertFalse(r2["refused"])

    def test_high_coverage_query_never_triggers(self):
        """已命中查询绝不触发语义桥（零回归守卫）。"""
        factory, client = fake_factory('{"terms": ["reconciliation"]}')
        semantic_bridge._client = factory
        r = self.searcher.query("reconciliation writeoff policy", top_k=6, semantic=True)
        self.assertFalse(r["refused"])
        self.assertEqual(client.calls, 0)
        self.assertIsNone(r["semantic_bridge"])

    def test_partial_coverage_cjk_query_fires(self):
        """触发门修订后的核心人群：cov∈[30%,60%) 且含 CJK——返回了结果但弱覆盖。
        语义桥并入扩展词重打分（不再只是拒答救援）。"""
        factory, client = fake_factory(
            '{"terms": ["reconciliation", "writeoff", "settlement", "policy"]}')
        semantic_bridge._client = factory
        # writeoff+对账 在图，差异/核销 缺席 → cov=2/4=50%<60%，且查询含 CJK
        r = self.searcher.query("writeoff 对账 差异 核销", top_k=6, semantic=True)
        self.assertEqual(client.calls, 1, "弱覆盖中文查询必须触发语义桥")
        self.assertFalse(r["refused"])
        self.assertIsNotNone(r["semantic_bridge"])

    def test_high_coverage_cjk_query_no_fire(self):
        """cov≥60% 的中文查询不触发（成本纪律：覆盖足够的查询不需要桥）。"""
        factory, client = fake_factory('{"terms": ["reconciliation"]}')
        semantic_bridge._client = factory
        r = self.searcher.query("writeoff 对账", top_k=6, semantic=True)
        self.assertEqual(client.calls, 0)
        self.assertFalse(r["refused"])
        self.assertIsNone(r["semantic_bridge"])

    def test_cli_flag_wired(self):
        """--semantic flag 被接受且不影响已命中查询（无网络路径）。"""
        env = dict(os.environ)
        env.pop(semantic_bridge.BRIDGE_ENV, None)
        p = subprocess.run(
            [sys.executable, "-B", "-m", "domimap", "query",
             "reconciliation writeoff policy", "-g", self.graph_path, "--semantic"],
            capture_output=True, text=True, cwd=ROOT, env=env, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("recon.md", p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
