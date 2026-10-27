"""product-ui-workbench：工作台页面 + 只读 API 契约（F2 同源同序；R08 只读边界）。

覆盖：13 条工作流全部在页面枚举；7 条可运行工作流的 API 行为与错误态；
非回环 Host 对新端点同样拒绝；页面去 AI 味与无超文本注入（无 innerHTML 字样）。
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
# 回环 HTTP 测试不受系统代理干扰（评审 RV08：本机默认代理曾使回环请求 502）
import urllib.request as _ur
_ur.install_opener(_ur.build_opener(_ur.ProxyHandler({})))

import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import domimap.lite_scan as ls  # noqa: E402
from domimap.graph import Graph, load_seeds  # noqa: E402
from domimap.ui import make_server  # noqa: E402

WORKFLOW_NAMES = ["检索问答", "需求定位卡", "问题排查卡", "影响面分析", "领域地图",
                  "证据阅读", "笔记沉淀", "反馈与历史", "工作区建图", "增量更新", "嵌入索引",
                  "LLM 草稿笔记", "人审队列导出", "MCP 客户端接入"]
AI_FLAVOR_WORDS = ["智能", "助手", "大模型", "✨", "🤖"]


def build_tmp_graph():
    tmp = tempfile.mkdtemp(prefix="dm-wb-")
    ws = os.path.join(tmp, "mini")
    shutil.copytree(os.path.join(HERE, "fixtures", "mini"), ws)
    records = ls.scan_repo(ws, repo_label="mini")
    g = Graph()
    g.build_from_records(records, load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
    gp = os.path.join(tmp, "graph.json")
    g.save(gp)
    return tmp, gp, g


class TestEvidenceBackedWorkbench(unittest.TestCase):
    """--discover 建图（有 store.db）时：候选带 ev、node= 直读固化片段。"""

    @classmethod
    def setUpClass(cls):
        import tempfile
        from domimap import batch
        tmp = tempfile.mkdtemp(prefix="dm-wb-ev-")
        roots = batch.discover_roots(os.path.join(HERE, "fixtures"))
        cls.srv = None
        if roots:
            g, _, _ = batch.build_many(roots, tmp, force=True, merged_name="graph")
            gp = os.path.join(tmp, "graph.json")
            if g is not None and os.path.exists(os.path.join(tmp, "store.db")):
                cls.gp, cls.srv = gp, make_server(gp, port=0)
                cls.port = cls.srv.server_address[1]
                threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        if cls.srv:
            cls.srv.shutdown()

    def _jget(self, path):
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:%d%s" % (self.port, path), timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_search_seeds_carry_ev_and_node_read_returns_blob(self):
        if not self.srv:
            self.skipTest("fixtures 无子仓（discover 不可用）")
        _, d = self._jget("/api/search?q=" + urllib.parse.quote("订单改价"))
        with_ev = [s for s in d["seeds"] if s.get("ev")]
        self.assertTrue(with_ev, "有证据库时候选应携带可读 ev ID")
        # 取首个带证据的候选（retrieval-identifier-boost-scope 后「订单改价」top6 由
        # PRD/改价链路节点占据，不再必然含 Table——证据链契约与候选类型无关）
        code, ev = self._jget("/api/read?node=" + urllib.parse.quote(with_ev[0]["id"]))
        self.assertEqual(code, 200)
        self.assertTrue(ev["available"])
        self.assertTrue(ev["text"], "固化片段应有原文")
        self.assertTrue(ev["ev_id"].startswith("ev:"))

    def test_read_node_without_evidence_is_honest(self):
        if not self.srv:
            self.skipTest("fixtures 无子仓（discover 不可用）")
        code, d = self._jget("/api/read?node=no:such:node")
        self.assertEqual(code, 404)
        self.assertIn("无此节点", d["reason"])


class TestUiWorkbench(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.gp, cls.g = build_tmp_graph()
        cls.srv = make_server(cls.gp, port=0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _get(self, path, headers=None):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path),
                                     headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode("utf-8", "replace")

    def _jget(self, path, headers=None):
        code, hdrs, body = self._get(path, headers)
        return code, json.loads(body) if body else {}

    # ---------- 页面 ----------

    def test_page_is_workbench_and_enumerates_all_workflows(self):
        code, hdrs, html = self._get("/")
        self.assertEqual(code, 200)
        self.assertIn("domimap 工作台", html)
        self.assertIn("工作台直接运行", html)
        self.assertIn("终端命令", html)
        for name in WORKFLOW_NAMES:
            self.assertIn(name, html, "工作流未枚举：" + name)
        # 7 条可运行 + 6 条命令型都给出真实命令线索
        self.assertIn("--discover", html)
        self.assertIn("domimap enrich", html)
        self.assertIn("domimap serve", html)

    def test_page_stats_injected_and_csp_header(self):
        code, hdrs, html = self._get("/")
        self.assertEqual(code, 200)
        self.assertIn('"name": "graph.json"', html)   # 服务端注入的图名/规模 JSON
        self.assertIn('"nodes": %d' % len(self.g.nodes), html)
        self.assertIn('"edges": %d' % len(self.g.edges), html)
        csp = hdrs.get("Content-Security-Policy", "")
        self.assertIn("default-src 'none'", csp)

    def test_page_no_html_injection_and_no_ai_flavor(self):
        _, _, html = self._get("/")
        self.assertIn("textContent", html)
        self.assertNotIn("innerHTML", html)
        for w in AI_FLAVOR_WORDS:
            self.assertNotIn(w, html, "页面出现 AI 味用语：" + w)

    # ---------- 可运行工作流 API ----------

    def test_search_returns_seeds_in_contract_shape(self):
        code, d = self._jget("/api/search?q=" + urllib.parse.quote("订单"))
        self.assertEqual(code, 200)
        self.assertTrue(d["seeds"])
        for s in d["seeds"]:
            # ev/conf 为可选字段：ev 仅在有固化证据时出现；conf 用于知识笔记来源标识
            self.assertTrue(set(s.keys()) <= {"file", "id", "kind", "name", "ev", "conf", "domain",
                                              "time_note", "era_source", "valid_until", "stale"})  # 时效/陈旧字段可选（F4/R06）
            for k in ("file", "id", "kind", "name"):
                self.assertIn(k, s)

    def test_scenario_req_card(self):
        code, d = self._jget("/api/scenario?kind=req&text=" + urllib.parse.quote("订单改价 防并发"))
        self.assertEqual(code, 200)
        self.assertTrue(d["card"].startswith("# 需求定位卡"))

    def test_scenario_trb_card(self):
        code, d = self._jget("/api/scenario?kind=trb&text=" + urllib.parse.quote("订单超时未支付"))
        self.assertEqual(code, 200)
        self.assertTrue(d["card"].startswith("# 排障卡"))

    def test_scenario_bad_params(self):
        code, d = self._jget("/api/scenario?kind=xx&text=" + urllib.parse.quote("任意"))
        self.assertEqual(code, 400)
        self.assertIn("error", d)
        code, d = self._jget("/api/scenario?kind=req&text=%20%20")
        self.assertEqual(code, 400)

    def test_impact_found_and_missing(self):
        code, d = self._jget("/api/impact?symbol=t_order")
        self.assertEqual(code, 200)
        self.assertTrue(d["start"])
        self.assertIn("deps", d)
        self.assertIn("total", d)
        code, d = self._jget("/api/impact?symbol=no_such_symbol_zzz")
        self.assertEqual(code, 404)
        self.assertEqual(d["error"], "无匹配符号")
        code, d = self._jget("/api/impact?symbol=")
        self.assertEqual(code, 400)
        code, d = self._jget("/api/impact?symbol=t_order&depth=abc")
        self.assertEqual(code, 400)

    def test_domain_map_endpoint(self):
        code, d = self._jget("/api/domain")
        self.assertEqual(code, 200)
        self.assertTrue(d["domains"])
        self.assertNotIn("__shared__", d["domains"])
        self.assertIsInstance(d["shared"], list)
        for a in d["domains"].values():
            for k in ("services", "tables", "topics", "docs"):
                self.assertIn(k, a)

    def test_read_by_sid_without_store_is_honest(self):
        code, d = self._jget("/api/read?sid=tbl:t_order")
        self.assertEqual(code, 404)
        self.assertFalse(d.get("available", True))
        self.assertTrue(d.get("reason"), "不可用时必须给出原因，不冒充内容")
        code, d = self._jget("/api/read")
        self.assertEqual(code, 400)

    def test_stats_endpoint_shape(self):
        code, d = self._jget("/api/stats")
        self.assertEqual(code, 200)
        self.assertEqual(d["nodes"], len(self.g.nodes))
        self.assertIn("store", d)
        self.assertIn("notes", d)
        self.assertIn("embed", d)

    def test_note_save_then_immediately_searchable(self):
        # 与 CLI 同源挂接 + 保存后即时重挂（长驻服务不重启）
        body = {"body": "即时检索自测标记：mq 主题重试幂等结论", "claims": [],
                "idempotency_key": "wb-note-1"}
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/note/save" % self.port,
            data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1"})
        with urllib.request.urlopen(req, timeout=10) as r:
            self.assertEqual(r.status, 200)
        code, d = self._jget("/api/search?q=" + urllib.parse.quote("即时检索自测标记"))
        kn = [s for s in d["seeds"] if s["kind"] == "Knowledge"]
        self.assertTrue(kn, "笔记保存后应立即可检索（attach_knowledge 重挂）")
        # 知识笔记节点 → 证据阅读：如实无固化文件证据
        code, d = self._jget("/api/read?node=" + urllib.parse.quote(kn[0]["id"]))
        self.assertEqual(code, 404)
        self.assertIn("固化", d["reason"])

    def test_new_endpoints_reject_foreign_host(self):
        code, _, _ = self._get("/api/domain", headers={"Host": "evil.example.com"})
        self.assertEqual(code, 403)
        code, _, _ = self._get("/api/impact?symbol=t_order", headers={"Host": "evil.example.com"})
        self.assertEqual(code, 403)
        code, _, _ = self._get("/api/scenario?kind=req&text=x", headers={"Host": "evil.example.com"})
        self.assertEqual(code, 403)


if __name__ == "__main__":
    unittest.main()
