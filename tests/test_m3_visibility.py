"""M3.2 知识检索可见性（AC-R05-02）：新会话命中 / 重建不丢 / 类型不混。"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from domimap.graph import Graph, load_seeds  # noqa: E402
from domimap.knowledge import KnowledgeStore  # noqa: E402
from domimap.search import Searcher  # noqa: E402

SEEDS = os.path.join(ROOT, "domimap", "seeds.json")
G_PATH = os.path.join(HERE, "out_shared", "graph.json")

TYPES = ["requirement", "implementation", "observation", "decision", "inference"]

def seed_kb(kb):
    for i in range(10):
        kb.submit(body="知识-%d 改价链路结论 marker-kn-%d：需带乐观锁" % (i, i),
                  claims=[{"type": TYPES[i % 5], "statement": "claim-%d" % i,
                           "evidence": [], "scope": "订单域"}],
                  idempotency_key="kn%d" % i)

class TestKnowledgeVisibility(unittest.TestCase):
    def test_new_session_hits_and_rebuild_keeps(self):
        with tempfile.TemporaryDirectory() as tmp:
            kb = KnowledgeStore(os.path.join(tmp, "kb.db"))
            seed_kb(kb)
            # 新会话：全新 Searcher + 重载机器图 + attach
            g = Graph.load(G_PATH)
            s = Searcher(g)
            s.attach_knowledge(kb)
            r = s.query("marker-kn-3 乐观锁", top_k=5)
            kn = [n for n in r["seeds"] if n["kind"] == "Knowledge"]
            self.assertTrue(kn, "新会话检索必须命中人工知识")
            # 机器图重建（force 全量）→ 知识库不受影响
            from domimap import batch
            roots = batch.discover_roots(os.path.join(HERE, "fixtures"))
            batch.build_many(roots, os.path.join(tmp, "out"), force=True, merged_name="m")
            self.assertEqual(kb.count(), 10, "机器重建不得触碰人工知识")
            s2 = Searcher(batch.build_many(roots, os.path.join(tmp, "out2"), force=True,
                                           merged_name="m")[0])
            s2.attach_knowledge(kb)
            r2 = s2.query("marker-kn-7 乐观锁", top_k=5)
            self.assertTrue([n for n in r2["seeds"] if n["kind"] == "Knowledge"])

    def test_types_never_become_facts_and_withdrawn_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            kb = KnowledgeStore(os.path.join(tmp, "kb.db"))
            seed_kb(kb)
            kb.withdraw("note:x")  # 不存在也无妨
            nid = kb.submit(body="撤回测试 marker-kn-w", claims=[{"type": "decision",
                                 "statement": "w", "evidence": [], "scope": "s"}],
                            idempotency_key="kw")["note_id"]
            kb.withdraw(nid)
            g = Graph.load(G_PATH)
            s = Searcher(g); s.attach_knowledge(kb)
            r = s.query("marker-kn-w", top_k=5)
            self.assertFalse([n for n in r["seeds"] if n.get("id") == "kn:" + nid],
                             "withdrawn 不进检索")
            r3 = s.query("marker-kn-1", top_k=5)
            for n in r3["seeds"]:
                for c in (n["meta"].get("claims") or []):
                    self.assertIn(c["type"], TYPES)
                    self.assertNotIn(c["type"], ("extracted", "fact"), "人工类型不得混为抽取事实")

if __name__ == "__main__":
    unittest.main()
