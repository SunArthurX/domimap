"""ui-note-validation：/api/note/save 参数校验 + Enter 提交与画布竞态守卫（R08/F2）。

空参不静默：缺 body/纯空白正文/claims 非数组一律 4xx，不创建垃圾笔记进检索池；
运行面板 Enter 触发运行（isComposing 守卫 + textarea Shift+Enter 换行）；
finishRun 的 CUR 守卫防止迟到响应污染切换后的新画布。
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import domimap.lite_scan as ls  # noqa: E402
from domimap.graph import Graph, load_seeds  # noqa: E402
from domimap.ui import make_server  # noqa: E402


def build_tmp_graph():
    tmp = tempfile.mkdtemp(prefix="dm-noteval-")
    ws = os.path.join(tmp, "mini")
    shutil.copytree(os.path.join(HERE, "fixtures", "mini"), ws)
    g = Graph()
    g.build_from_records(ls.scan_repo(ws, repo_label="mini"),
                         load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
    gp = os.path.join(tmp, "graph.json")
    g.save(gp)
    return tmp, gp, g


class TestNoteApiValidation(unittest.TestCase):
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

    def _post(self, payload):
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/note/save" % self.port,
            data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def _note_count(self):
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/api/stats" % self.port, timeout=10) as r:
            return json.loads(r.read())["notes"] or 0

    def test_missing_body_rejected_without_create(self):
        """原缺陷用例：{"claims":[]} 曾 200 建空笔记——必须 400 且计数不变。"""
        before = self._note_count()
        code, d = self._post({"claims": []})
        self.assertEqual(code, 400)
        self.assertIn("正文不能为空", d["error"])
        self.assertEqual(self._note_count(), before, "非法请求不得创建笔记")

    def test_blank_body_rejected(self):
        before = self._note_count()
        code, d = self._post({"body": "   ", "idempotency_key": "blank-1"})
        self.assertEqual(code, 400)
        self.assertEqual(self._note_count(), before)

    def test_claims_non_list_rejected(self):
        code, d = self._post({"body": "正文", "claims": "not-a-list"})
        self.assertEqual(code, 400)
        self.assertIn("claims", d["error"])

    def test_valid_save_and_idempotent_replay_unchanged(self):
        code, d = self._post({"body": "校验后合法保存：改价先查影响面",
                              "claims": [], "idempotency_key": "valid-1"})
        self.assertEqual(code, 200)
        self.assertTrue(d["note_id"].startswith("note:"))
        code2, d2 = self._post({"body": "校验后合法保存：改价先查影响面",
                                "claims": [], "idempotency_key": "valid-1"})
        self.assertEqual(code2, 200)
        self.assertEqual(d2["note_id"], d["note_id"], "同 key 同文幂等去重不回归")


class TestPageGuards(unittest.TestCase):
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

    def test_page_has_enter_and_finishrun_guards(self):
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/" % self.port, timeout=10) as r:
            html = r.read().decode("utf-8")
        self.assertIn("isComposing", html, "Enter 提交必须带输入法组词守卫")
        self.assertIn("shiftKey", html, "textarea 需保留 Shift+Enter 换行")
        self.assertIn('if(CUR!==wf) return;', html, "finishRun 必须有切换守卫")
        self.assertNotIn("innerHTML", html)


if __name__ == "__main__":
    unittest.main()
