"""search-refusal-reason：拒答原因诚实化契约（R01 如实告知 / R04 检索语义）。

拒答分支条件是 cov < min_cov or not scored or not strong 三者之一；
文案必须按真实触发条件分化——域过滤筛空候选时不得谎称"覆盖率不足"
（覆盖率明明达标时会自相矛盾并误导排障方向）。
消费方（CLI exit 3 / MCP / UI）均以 refused 标志为准，不解析文案。
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import domimap.lite_scan as ls  # noqa: E402
from domimap.graph import Graph, load_seeds  # noqa: E402
from domimap.search import Searcher  # noqa: E402
from domimap.ui import make_server  # noqa: E402

REFUSE_MARK = "诚实拒答"


def build_searcher_and_graph():
    tmp = tempfile.mkdtemp(prefix="dm-refusal-")
    ws = os.path.join(tmp, "mini")
    shutil.copytree(os.path.join(HERE, "fixtures", "mini"), ws)
    g = Graph()
    g.build_from_records(ls.scan_repo(ws, repo_label="mini"),
                         load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
    gp = os.path.join(tmp, "graph.json")
    g.save(gp)
    return tmp, gp, g, Searcher(g)


class TestRefusalReasonDifferentiation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.gp, cls.g, cls.s = build_searcher_and_graph()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_domain_filter_refusal_names_domain_not_coverage(self):
        """覆盖率达标但域过滤筛空 → 点名域值，不得谎称覆盖率不足。"""
        base = self.s.query("订单", top_k=6, expand=False)
        self.assertFalse(base.get("refused"), "前提：无域过滤时该查询应有候选")
        r = self.s.query("订单", top_k=6, expand=False, domain="不存在的域")
        self.assertTrue(r.get("refused"))
        self.assertIn(REFUSE_MARK, r["text"])
        self.assertIn("域过滤", r["text"])
        self.assertIn("不存在的域", r["text"], "拒答文案必须点名域值本身")
        self.assertNotIn("阈值", r["text"], "覆盖率达标时不得谎称覆盖率不足阈值")

    def test_low_coverage_refusal_keeps_coverage_reason(self):
        """真覆盖率不足 → 保留覆盖率文案（不能因分化丢失原因）。"""
        r = self.s.query("量子纠缠玄学术语毫无关系", top_k=6, expand=False)
        self.assertTrue(r.get("refused"))
        self.assertIn(REFUSE_MARK, r["text"])
        self.assertIn("覆盖率", r["text"])
        self.assertIn("阈值", r["text"])
        self.assertNotIn("域过滤", r["text"], "无域过滤时不得甩锅域过滤")


class TestApiRefusalReasonAndPageGuard(unittest.TestCase):
    """/api/search 拒答原因经 API 同源透出；页面前缀与输入长度护栏。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.gp, cls.g, cls.s = build_searcher_and_graph()
        cls.srv = make_server(cls.gp, port=0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _jget(self, path):
        import urllib.error
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:%d%s" % (self.port, path), timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_api_domain_refusal_is_honest(self):
        code, d = self._jget("/api/search?q=" + urllib.parse.quote("订单")
                             + "&domain=" + urllib.parse.quote("NoSuchDomain"))
        self.assertEqual(code, 200)
        self.assertTrue(d["refused"])
        self.assertIn("域过滤", d["text"])
        self.assertIn("NoSuchDomain", d["text"])

    def test_page_refusal_prefix_and_length_guard(self):
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/" % self.port, timeout=10) as r:
            html = r.read().decode("utf-8")
        self.assertIn('"拒答："+(d.text||"")', html,
                      "拒答前缀不得再硬编码原因（原因由后端 text 给出）")
        self.assertNotIn("拒答（覆盖率不足）", html)
        self.assertIn("输入过长（上限 2000 字符）", html, "GET 工作流应有前端长度护栏")
        self.assertIn("无依据时明确说不知道", html)
        self.assertNotIn("innerHTML", html)


if __name__ == "__main__":
    unittest.main()
