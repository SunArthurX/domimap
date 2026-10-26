"""ui-stats-fresh-load：页眉统计随每次页面加载刷新（R01 如实呈现）。

长驻 `domimap ui` 的 `/` 曾返回启动时一次性渲染的整页（stats 冻结快照）：
保存笔记后刷新页面看不到笔记数。契约：新加载页面的注入 STATS 即时反映
knowledge.db 当前状态，无需任何客户端刷新。
"""
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import domimap.lite_scan as ls  # noqa: E402
from domimap.graph import Graph, load_seeds  # noqa: E402
from domimap.ui import make_server  # noqa: E402


def build_tmp_graph():
    tmp = tempfile.mkdtemp(prefix="dm-stats-")
    ws = os.path.join(tmp, "mini")
    shutil.copytree(os.path.join(HERE, "fixtures", "mini"), ws)
    g = Graph()
    g.build_from_records(ls.scan_repo(ws, repo_label="mini"),
                         load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
    gp = os.path.join(tmp, "graph.json")
    g.save(gp)
    return tmp, gp, g


class TestStatsFreshOnLoad(unittest.TestCase):
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

    def _stats_injected(self):
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/" % self.port, timeout=10) as r:
            html = r.read().decode("utf-8")
        m = re.search(r"const STATS = (\{.*?\});", html, re.S)
        self.assertTrue(m, "页面应注入 STATS JSON")
        return json.loads(m.group(1).replace("<\\/}", "</}") if "<\\/" in m.group(1) else m.group(1))

    def _save_note(self, key):
        body = {"body": "页眉即时可见自测 " + key, "claims": [], "idempotency_key": key}
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/note/save" % self.port,
            data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1"})
        with urllib.request.urlopen(req, timeout=10) as r:
            self.assertEqual(r.status, 200)

    def test_fresh_load_shows_notes_without_client_refresh(self):
        """保存后全新加载页面：注入 STATS 即含新笔记数（不靠保存后的 refreshStats）。"""
        first = self._stats_injected()
        base = first.get("notes") or 0
        self._save_note("stats-fresh-1")
        second = self._stats_injected()
        self.assertEqual(second.get("notes"), base + 1,
                         "新加载页面的 STATS 必须实时：got %r want %r" % (second.get("notes"), base + 1))
        # /api/stats 与页面注入一致
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/api/stats" % self.port, timeout=10) as r:
            live = json.loads(r.read())
        self.assertEqual(live["notes"], second["notes"])

    def test_no_knowledge_db_page_still_renders(self):
        """knowledge.db 不存在（首启）时页面正常、notes=null 不冒异常文案。"""
        tmp, gp, g = build_tmp_graph()
        srv = make_server(gp, port=0)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:%d/" % port, timeout=10) as r:
                html = r.read().decode("utf-8")
            self.assertIn("domimap 工作台", html)
            self.assertIn('"notes": null', html)
        finally:
            srv.shutdown()
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
