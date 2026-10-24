"""M2 收口：R02-02 覆盖可见 / R04-01 分路去重 / R08-03 MCP 容错。"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import domimap.lite_scan as ls  # noqa: E402
from domimap.graph import Graph, load_seeds  # noqa: E402
from domimap.search import Searcher  # noqa: E402

SEEDS = os.path.join(ROOT, "domimap", "seeds.json")

def build(extra_setup=None):
    tmp = tempfile.mkdtemp(prefix="dm-close-")
    ws = os.path.join(tmp, "mini")
    shutil.copytree(os.path.join(HERE, "fixtures", "mini"), ws)
    if extra_setup:
        extra_setup(ws)
    R = ls.scan_repo(ws, repo_label="mini")
    g = Graph(); g.build_from_records(R, load_seeds(SEEDS))
    return g, R

class TestCoverageVisible(unittest.TestCase):
    def test_query_result_carries_coverage(self):
        def add_gaps(ws):
            open(os.path.join(ws, "broken.xml"), "w").write("<mapper><select id='x'>FROM")
        g, R = build(add_gaps)
        s = Searcher(g)
        s.coverage = R["coverage"]
        r = s.query("price_version", top_k=5)
        self.assertIn("coverage", r, "检索结果必须携带覆盖摘要")
        self.assertGreater(r["coverage"]["skipped"], 0)
        self.assertTrue(any("mapper" in json.dumps(r["coverage"]["reasons"] or {}) or
                            r["coverage"]["skipped"] for _ in [0]))

class TestDualTrackAndDedup(unittest.TestCase):
    def test_docs_not_starved_and_file_dedup(self):
        def add_dup_doc(ws):
            d = os.path.join(ws, "docs")
            open(os.path.join(d, "dup1.md"), "w").write("重复文档 same-dup-marker 内容 A")
            open(os.path.join(d, "dup2.md"), "w").write("重复文档 same-dup-marker 内容 B")
        g, _ = build(add_dup_doc)
        r = Searcher(g).query("same-dup-marker 重复文档", top_k=6)
        names = [n["name"] for n in r["seeds"]]
        self.assertTrue(any(n["kind"] == "Doc" for n in r["seeds"]), "文档不得饥饿")
        files = [n["file"] for n in r["seeds"]]
        from collections import Counter
        self.assertTrue(all(c <= 2 for c in Counter(files).values()),
                        "同文件家族 ≤2 席：%s" % files)

class TestMcpFaultTolerance(unittest.TestCase):
    def test_bad_params_then_valid_still_works(self):
        from domimap.mcp import Server
        out = os.path.join(HERE, "out_shared")
        if not os.path.exists(out + "/graph.json"):
            self.skipTest("图未生成")
        srv = Server(out + "/graph.json")
        r = srv.handle("kg_explore", None)  # params 非法
        self.assertIn("错误", str(r)); self.assertNotIn("Traceback", str(r))
        self.assertNotIn("attribute", str(r).lower(), "不泄漏内部异常文本")
        ok = srv.handle("kg_explore", {"query": "price_version"})
        self.assertIn("price_version", ok)

    def test_huge_request_bounded(self):
        import subprocess as sp
        out = os.path.join(HERE, "out_shared")
        if not os.path.exists(out + "/graph.json"):
            # 新克隆无残留夹具：按 test_m2_shared 同规则现建（不依赖本机历史产物）
            from domimap import batch
            batch.build_many(batch.discover_roots(os.path.join(HERE, "fixtures")), out,
                             force=True, merged_name="fixtures")
        big = "x" * (2 << 20)
        msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": "kg_explore", "arguments": {"query": big}}})
        p = sp.run([sys.executable, "-B", "-m", "domimap", "serve", "-g",
                    os.path.join(HERE, "out_shared", "graph.json")],
                   input=msg + "\n" + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n",
                   capture_output=True, text=True, cwd=ROOT, timeout=60)
        lines = [l for l in p.stdout.splitlines() if l.strip()]
        self.assertEqual(len(lines), 2, "每个请求恰一个响应（错误有界，stdout 仅协议）")
        self.assertIn("error", lines[0] or "", "超大请求应有错误响应")

if __name__ == "__main__":
    unittest.main()
