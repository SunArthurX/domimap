"""记录缓存、工作区种子、服务全景与正向追踪。"""
import os
import shutil
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from domimap import lite_scan  # noqa: E402
from domimap.batch import build_many, normalized, update  # noqa: E402
from domimap.store import EvidenceStore  # noqa: E402
from domimap.graph import Graph, load_seeds, load_workspace_seeds  # noqa: E402


def _write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(text).lstrip("\n"))


class TestRecordCache(unittest.TestCase):
    def test_unchanged_repo_is_not_rescanned(self):
        tmp = tempfile.mkdtemp(prefix="dm-cache-")
        self.addCleanup(shutil.rmtree, tmp)
        ws = os.path.join(tmp, "ws")
        out = os.path.join(tmp, "out")
        _write(ws, "alpha/pom.xml", "<project><artifactId>alpha</artifactId></project>")
        _write(ws, "alpha/src/A.java", "package a; public class A { public void a() {} }")
        _write(ws, "beta/pom.xml", "<project><artifactId>beta</artifactId><dependencies><dependency><artifactId>alpha</artifactId></dependency></dependencies></project>")
        _write(ws, "beta/src/B.java", "package b; public class B { public void b() {} }")
        roots = [os.path.join(ws, "alpha"), os.path.join(ws, "beta")]
        g, _, _ = build_many(roots, out, force=True)
        self.assertTrue(any(e["kind"] == "DEPENDS_ON" and "beta" in e["src"] and "alpha" in e["dst"]
                            for e in g.edges), [e for e in g.edges if e["kind"] == "DEPENDS_ON"])
        seen = []
        orig = lite_scan.scan_repo

        def wrapped(root, *a, **k):
            seen.append(os.path.basename(os.path.abspath(root)))
            return orig(root, *a, **k)

        lite_scan.scan_repo = wrapped
        try:
            _write(ws, "beta/src/B.java", "package b; public class B { public void b() { } public void c() {} }")
            g2, _, results = update(out)
        finally:
            lite_scan.scan_repo = orig
        self.assertIsNotNone(g2)
        self.assertEqual(seen, ["beta"], seen)
        self.assertTrue(any(st == "no-op" for _, st in results), results)


class TestProcessScan(unittest.TestCase):
    def test_two_processes_match_inline_and_evidence_is_readable(self):
        tmp = tempfile.mkdtemp(prefix="dm-procs-")
        self.addCleanup(shutil.rmtree, tmp)
        ws = os.path.join(tmp, "ws")
        _write(ws, "alpha/pom.xml", "<project><artifactId>alpha</artifactId></project>")
        _write(ws, "alpha/src/A.java", "package a;\npublic class A { public void ping() {} }\n")
        _write(ws, "beta/pom.xml", "<project><artifactId>beta</artifactId><dependencies><dependency><artifactId>alpha</artifactId></dependency></dependencies></project>")
        _write(ws, "beta/src/B.java", "package b;\npublic class B { public void pong() {} }\n")
        roots = [os.path.join(ws, "alpha"), os.path.join(ws, "beta")]
        g1, _, _ = build_many(roots, os.path.join(tmp, "one"), jobs=1, force=True)
        g2, _, _ = build_many(roots, os.path.join(tmp, "two"), jobs=2, force=True)
        self.assertEqual(normalized(g1), normalized(g2))
        store = EvidenceStore(os.path.join(tmp, "two", "store.db"))
        self.addCleanup(store.close)
        ev = store.db.execute("SELECT ev_id FROM evidence LIMIT 1").fetchone()[0]
        got = store.read_evidence(ev)
        self.assertTrue(got["available"], got)
        self.assertTrue(got["text"])


class TestWorkspaceSeeds(unittest.TestCase):
    def test_workspace_file_overrides_domain_and_keeps_synonyms(self):
        tmp = tempfile.mkdtemp(prefix="dm-seeds-")
        self.addCleanup(shutil.rmtree, tmp)
        with open(os.path.join(tmp, "domimap.seeds.json"), "w", encoding="utf-8") as f:
            f.write('{"采购域": {"keywords": ["purchase", "采购"]}, "_synonyms": {"改价": ["adjustPrice"]}}')
        seeds = load_workspace_seeds(tmp)
        self.assertIn("采购域", seeds)
        self.assertIn("订单域", seeds)
        self.assertIn("adjustPrice", seeds["_synonyms"]["改价"])
        self.assertIn("price", seeds["_synonyms"]["改价"])


class TestTrace(unittest.TestCase):
    def test_forward_trace_reaches_table(self):
        R = lite_scan.scan_repo(os.path.join(HERE, "fixtures", "mini"), repo_label="mini")
        g = Graph()
        g.build_from_records(R, load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
        steps = g.trace("changePrice", depth=4)
        kinds = {s["kind"] for s in steps}
        self.assertIn("CALLS", kinds)
        self.assertTrue(kinds & {"CALLS_SQL", "WRITES", "READS"}, kinds)
        rels = g.service_map()["relations"]
        self.assertTrue(any(r["kind"] == "RPC" for r in rels), rels)


class TestGraphHealth(unittest.TestCase):
    def test_summarize_mini_graph(self):
        import json
        from scripts.graph_health import summarize_obj
        R = lite_scan.scan_repo(os.path.join(HERE, "fixtures", "mini"), repo_label="mini")
        g = Graph()
        g.build_from_records(R, load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
        doc = {"nodes": list(g.nodes.values()), "edges": g.edges}
        rec = summarize_obj(doc)
        self.assertGreater(rec["methods"], 0)
        self.assertLess(rec["calls_per_method"], 10, rec)
        self.assertEqual(rec["duplicate_edges"], 0)
        self.assertGreater(json.dumps(rec).__len__(), 10)


if __name__ == "__main__":
    unittest.main()
