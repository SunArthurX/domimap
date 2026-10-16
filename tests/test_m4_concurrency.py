"""M4.3 R10-01：8 在途读 + 串行保存/发布混合负载（无混代/丢写）。"""
import json
import os
import sys
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from domimap.graph import Graph  # noqa: E402
from domimap.knowledge import KnowledgeStore  # noqa: E402
from domimap.mcp import Server  # noqa: E402

G = os.path.join(HERE, "out_shared", "graph.json")

class TestMixedLoad(unittest.TestCase):
    def test_eight_readers_with_writes_and_publish(self):
        srv = Server(G)
        errs = []
        results = []

        def reader(i):
            try:
                for k in range(5):
                    out = srv.handle("kg_explore", {"query": "price_version", "top_k": 3})
                    if "price_version" not in out and "拒答" not in out:
                        raise AssertionError("reader %d got bad payload" % i)
                results.append(i)
            except Exception as e:  # noqa: BLE001
                errs.append(e)

        kb_path = G + ".concurrency-kb.db"
        if os.path.exists(kb_path):
            os.remove(kb_path)
        kb = KnowledgeStore(kb_path)

        def writer():
            try:
                for i in range(5):
                    kb.submit(body="并发笔记 %d" % i, claims=[], idempotency_key="conc%d" % i)
            except Exception as e:  # noqa: BLE001
                errs.append(e)

        def publisher():
            try:
                from domimap.store import EvidenceStore
                st = EvidenceStore(os.path.join(HERE, "out_shared", "store.db"))
                g2 = Graph(); g2.add_node("pub-%d" % os.getpid(), "Service", "s", "f"); g2.index()
                st.publish_graph(g2, extra_meta={"concurrent": True})
                st.close()
            except Exception as e:  # noqa: BLE001
                errs.append(e)

        threads = [threading.Thread(target=reader, args=(i,)) for i in range(8)]
        threads += [threading.Thread(target=writer), threading.Thread(target=publisher)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertFalse(errs, errs)
        self.assertEqual(len(results), 8, "全部读者成功")
        self.assertEqual(kb.count(), 5, "串行保存写入不丢")
        from domimap.store import EvidenceStore
        st = EvidenceStore(os.path.join(HERE, "out_shared", "store.db"))
        act = st.active_generation()
        self.assertIsNotNone(act, "并发后 active 完整（无混代）")
        st.close()

if __name__ == "__main__":
    unittest.main()
