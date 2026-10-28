"""旧代和未被引用的 blob 可以清掉；当前代和已登记证据留下来。"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from domimap.graph import Graph  # noqa: E402
from domimap.store import EvidenceStore  # noqa: E402


class TestPrune(unittest.TestCase):
    def test_old_generation_goes_and_referenced_blob_stays(self):
        tmp = tempfile.mkdtemp(prefix="dm-gc-")
        self.addCleanup(shutil.rmtree, tmp)
        store = EvidenceStore(os.path.join(tmp, "store.db"))
        self.addCleanup(store.close)
        for name in ("a", "b"):
            g = Graph()
            g.add_node("doc:" + name, "Doc", name, name + ".md", {"text": name})
            store.publish_graph(g)
        gens = [n for n in os.listdir(os.path.join(tmp, "gens")) if n.startswith("gen-")]
        self.assertEqual(sorted(gens), ["gen-0001.json", "gen-0002.json"])
        removed = store.prune_generations(keep=1)
        self.assertEqual(removed, [1])
        self.assertFalse(os.path.exists(os.path.join(tmp, "gens", "gen-0001.json")))
        self.assertIsNotNone(store.active_generation())
        orphan = "ab" * 32
        with open(os.path.join(store.blobs, orphan), "wb") as f:
            f.write(b"orphan")
        rec = store.capture_source("repo", "repo|a.md", os.path.join(tmp, "a.md"), "a.md", raw=b"hello")
        gone = store.prune_unreferenced_blobs()
        self.assertIn(orphan, gone)
        self.assertTrue(os.path.exists(os.path.join(store.blobs, rec["sha256"])))
        self.assertFalse(os.path.exists(os.path.join(store.blobs, orphan)))


if __name__ == "__main__":
    unittest.main()
