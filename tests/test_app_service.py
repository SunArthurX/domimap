"""公共应用服务（product#6 / AC-R04-02 / AC-F2-01）：三入口同参、同错、同预算、同热重载。

此前：UI expand=False 与 CLI/MCP 不同；kg_doc_search 绕过 run_query 且 8/6000/无 seeds；impact 预算只有 MCP
执行；UI /api/search 无异常处理（异常=无 HTTP 响应）；UI 不热重载图。
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from domimap import mcp, service
from domimap.graph import Graph, build as graph_build
from domimap.ui import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MINI = os.path.join(HERE, "fixtures", "mini")
Q = "订单改价 防并发"


def _events(ws):
    db = sqlite3.connect(os.path.join(ws, "queries.db"))
    try:
        return db.execute("SELECT entry, params_json, status FROM query_events ORDER BY rowid").fetchall()
    finally:
        db.close()


class _UI:
    def __init__(self, gp):
        self.srv = make_server(gp, port=0)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def get(self, path):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), headers={"Host": "127.0.0.1"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


class TestAppService(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dm-svc-")
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.ws = os.path.join(self.tmp, "ws")
        self.g, _ = graph_build(MINI, self.ws)
        self.gp = os.path.join(self.ws, "graph.json")
        os.environ.pop("DOMIMAP_OBSERVE", None)

    def _effective(self, params_json):
        p = json.loads(params_json)
        return {k: p.get(k) for k in ("top_k", "expand", "budget", "min_cov", "domain")}

    def test_three_entries_record_identical_effective_params(self):
        p = subprocess.run([sys.executable, "-B", "-m", "domimap", "query", Q, "-g", self.gp],
                           cwd=ROOT, capture_output=True, text=True)
        self.assertIn(p.returncode, (0, 3), p.stderr)
        srv = mcp.Server(self.gp)
        self.assertFalse(srv.call("kg_explore", {"query": Q})["isError"])
        ui = _UI(self.gp)
        self.addCleanup(ui.close)
        code, body = ui.get("/api/search?q=" + urllib.request.quote(Q))
        self.assertEqual(code, 200)
        evs = _events(self.ws)
        self.assertEqual([e[0] for e in evs], ["cli", "mcp", "ui"])
        effective = {self._effective(e[1]) and json.dumps(self._effective(e[1]), sort_keys=True) for e in evs}
        self.assertEqual(len(effective), 1, "三入口有效参数必须完全一致：%s" % evs)
        self.assertEqual(json.loads(evs[0][1]).get("expand"), service.QUERY_DEFAULTS["expand"])

    def test_ui_internal_error_is_a_json_500_not_a_dropped_connection(self):
        ui = _UI(self.gp)
        self.addCleanup(ui.close)
        original = service.AppService.query

        def boom(self_svc, text, entry, **kw):
            raise RuntimeError("injected searcher failure")

        service.AppService.query = boom
        try:
            code, body = ui.get("/api/search?q=x")
        finally:
            service.AppService.query = original
        self.assertEqual(code, 500)
        self.assertEqual(body.get("code"), "internal")
        self.assertIn("error", body)
        self.assertNotIn("injected", body["error"], "内部异常文本不外泄")

    def _hub_graph(self):
        g = Graph()
        g.add_node("tbl:hub", "Table", "hub", "db/hub.sql", {})
        for i in range(260):
            g.add_node("mth:s:C.m%d#0" % i, "Method", "m%d" % i, "s/C.java", {})
            g.add_edge("mth:s:C.m%d#0" % i, "tbl:hub", "READS", "EXTRACTED", "test")
        gp = os.path.join(self.tmp, "hub", "graph.json")
        g.save(gp)
        return gp

    def test_impact_budget_and_partial_are_shared_by_all_entries(self):
        gp = self._hub_graph()
        svc = service.AppService(gp)
        r = svc.impact("hub")
        self.assertTrue(r["partial"])
        self.assertEqual(r["total"], service.IMPACT_MAX_NODES)
        r2 = svc.impact("hub", max_nodes=300)
        self.assertFalse(r2["partial"])
        self.assertEqual(r2["total"], 260)
        with self.assertRaises(service.ServiceError):
            svc.impact("", 2)
        with self.assertRaises(service.ServiceError):
            svc.impact("hub", depth=99)
        # MCP
        out = json.loads(mcp.Server(gp).call("kg_impact", {"symbol": "hub"})["content"][0]["text"])
        self.assertTrue(out["partial"])
        self.assertEqual(out["total_deps"], service.IMPACT_MAX_NODES)
        # UI
        ui = _UI(gp)
        self.addCleanup(ui.close)
        code, body = ui.get("/api/impact?symbol=hub")
        self.assertEqual(code, 200)
        self.assertTrue(body["partial"], body.keys())
        self.assertEqual(body["total"], service.IMPACT_MAX_NODES)
        # CLI
        p = subprocess.run([sys.executable, "-B", "-m", "domimap", "impact", "hub", "-g", gp],
                           cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("partial", p.stdout, "CLI 也须显式标注预算截断")
        self.assertIn("--READS(EXTRACTED)--> hub", p.stdout, "CLI 打印：src --KIND(路径强度)--> dst（修正此前 dst/conf 错位）")

    def test_ui_hot_reloads_graph_and_knowledge_changes(self):
        ui = _UI(self.gp)
        self.addCleanup(ui.close)
        code, body = ui.get("/api/search?q=" + urllib.request.quote("zzqwerty_unique_token"))
        self.assertEqual(code, 200)
        self.assertFalse(any("zzqwerty" in s["name"] for s in body["seeds"]))
        g2 = Graph.load(self.gp)
        g2.add_node("doc:(root):docs/zzqwerty_unique_token.md", "Doc", "zzqwerty_unique_token.md",
                    "docs/zzqwerty_unique_token.md", {"text": "zzqwerty_unique_token 说明文档 内容"})
        g2.save(self.gp)
        code, body = ui.get("/api/search?q=" + urllib.request.quote("zzqwerty_unique_token"))
        self.assertEqual(code, 200)
        self.assertTrue(any("zzqwerty" in s["name"] for s in body["seeds"]),
                        "graph.json 变化后长驻 UI 必须热重载：%s" % body)

    def test_doc_search_is_observed_and_has_cli_counterpart(self):
        srv = mcp.Server(self.gp)
        out = srv.call("kg_doc_search", {"query": "改价"})
        self.assertFalse(out["isError"])
        evs = _events(self.ws)
        self.assertEqual([e[0] for e in evs], ["mcp"], "kg_doc_search 必须经共享路径记录")
        p = json.loads(evs[0][1])
        self.assertEqual((p.get("top_k"), p.get("expand"), p.get("budget")),
                         (service.DOC_SEARCH_DEFAULTS["top_k"], service.DOC_SEARCH_DEFAULTS["expand"],
                          service.DOC_SEARCH_DEFAULTS["budget"]))
        cli = subprocess.run([sys.executable, "-B", "-m", "domimap", "doc", "改价", "-g", self.gp],
                             cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertIn("改价需求PRD.md", cli.stdout)
        evs = _events(self.ws)
        self.assertEqual([e[0] for e in evs], ["mcp", "cli"])
        self.assertEqual(self._effective(evs[0][1]), self._effective(evs[1][1]), "MCP/CLI 文档检索同参")


if __name__ == "__main__":
    unittest.main()
