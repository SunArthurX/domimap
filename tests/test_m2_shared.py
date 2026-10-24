"""M2.2：四入口同源同序 + Read/Trace 预算 partial（AC-F2-01 / AC-R04-02）。"""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from domimap import batch  # noqa: E402
from domimap.graph import Graph, load_seeds  # noqa: E402
from domimap.search import Searcher  # noqa: E402

OUT = os.path.join(HERE, "out_shared")
SEEDS = load_seeds(os.path.join(ROOT, "domimap", "seeds.json"))
Q = "价格同步监听"

_g = None
def G():
    global _g
    if _g is None:
        roots = batch.discover_roots(os.path.join(HERE, "fixtures"))
        _g, _, _ = batch.build_many(roots, OUT, force=True, merged_name="fixtures")
    return _g

def core_ids():
    r = Searcher(G()).query(Q, top_k=6, expand=False, seeds=SEEDS)
    return [n["id"] for n in r["seeds"]]

class TestSameSourceFourEntries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        G()  # 新克隆无 tests/out_shared 残留：先建图（字母序首个用例不触发惰性构建）

    def test_cli_text_matches_core(self):
        g = OUT + "/graph.json"
        p = subprocess.run([sys.executable, "-B", "-m", "domimap", "query", Q, "-g", g],
                           cwd=ROOT, capture_output=True, text=True)
        files = re.findall(r"@\s*(\S+)", p.stdout)
        core_files = [G().nodes[i]["file"] for i in core_ids()]
        self.assertEqual(files[:len(core_files)], core_files[:len(files)],
                         "CLI 文本主候选须与核心同源同序")

    def test_cli_json_matches_core(self):
        g = OUT + "/graph.json"
        p = subprocess.run([sys.executable, "-B", "-m", "domimap", "query", Q, "-g", g, "--json"],
                           cwd=ROOT, capture_output=True, text=True)
        d = json.loads(p.stdout)
        self.assertEqual([x["id"] for x in d["seeds"]], core_ids())

    def test_mcp_explore_matches_core(self):
        from domimap.mcp import Server
        srv = Server(OUT + "/graph.json")
        text = srv.handle("kg_explore", {"query": Q})
        files = re.findall(r"@\s*(\S+)", text)
        core_files = [G().nodes[i]["file"] for i in core_ids()]
        self.assertEqual(files[:len(core_files)], core_files[:len(files)],
                         "MCP kg_explore 须与核心同源同序（AC-F2-01）")

    def test_ui_http_matches_core(self):
        from domimap.ui import make_server
        srv = make_server(OUT + "/graph.json", port=0)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:%d/api/search?q=%s" % (port, urllib.parse.quote(Q)), timeout=10) as resp:
                d = json.loads(resp.read())
            self.assertEqual([x["id"] for x in d["seeds"]], core_ids())
        finally:
            srv.shutdown()

class TestBudgetsAndRead(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        G()  # 同上：用图前先确保夹具存在

    def test_impact_budget_partial(self):
        from domimap.mcp import Server
        srv = Server(OUT + "/graph.json")
        d = json.loads(srv.handle("kg_impact", {"symbol": "t_order", "max_nodes": 1}))
        self.assertTrue(d.get("partial"), "超预算必须显式 partial")
        self.assertIn("truncated", d)

    def test_read_unknown_id_explicit(self):
        from domimap.mcp import Server
        srv = Server(OUT + "/graph.json")
        d = json.loads(srv.handle("kg_read", {"ev_id": "ev:nonexistent0000"}).splitlines()[0])
        self.assertFalse(d.get("available", True))
        self.assertIn("reason", d)

if __name__ == "__main__":
    unittest.main()
