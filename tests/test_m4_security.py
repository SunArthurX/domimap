"""M4.2 R08-02：UI 脚本不执行 / 跨站写拒绝 / 回环写可用。"""
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

import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from domimap.ui import make_server  # noqa: E402


def corpus_with_evil_doc():
    tmp = tempfile.mkdtemp(prefix="dm-sec-")
    ws = os.path.join(tmp, "mini")
    shutil.copytree(os.path.join(HERE, "fixtures", "mini"), ws)
    with open(os.path.join(ws, "docs", "evil.md"), "w", encoding="utf-8") as f:
        f.write("evil-marker 文档 <script>alert(1)</script> <img src=x onerror=alert(2)>")
    import domimap.lite_scan as ls
    from domimap.graph import Graph, load_seeds
    R = ls.scan_repo(ws, repo_label="mini")
    g = Graph(); g.build_from_records(R, load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
    gp = os.path.join(tmp, "graph.json")
    g.save(gp)
    return tmp, gp


class TestUiSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.gp = corpus_with_evil_doc()
        cls.srv = make_server(cls.gp, port=0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def _get(self, path, headers=None):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.headers.get("Content-Type", ""), r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Content-Type", ""), e.read().decode("utf-8", "replace")

    def _post(self, path, body, headers=None):
        data = json.dumps(body).encode()
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=data,
                                     headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def test_evil_doc_returned_as_json_not_executed(self):
        code, ctype, body = self._get("/api/search?q=" + urllib.parse.quote("evil-marker 文档"))
        self.assertEqual(code, 200)
        self.assertTrue(ctype.startswith("application/json"), "资料按 JSON 数据返回，不作为 HTML 执行")
        d = json.loads(body)
        self.assertTrue(any("evil.md" in s["file"] for s in d["seeds"]))

    def test_page_uses_textcontent(self):
        _, _, html = self._get("/")
        self.assertIn("textContent", html)
        self.assertNotIn("innerHTML", html)

    def test_cross_origin_write_rejected_loopback_ok(self):
        body = {"body": "安全笔记", "claims": [], "idempotency_key": "sec1"}
        code, _ = self._post("/api/note/save", body,
                             headers={"Origin": "https://evil.example.com"})
        self.assertEqual(code, 403, "跨站来源写入必须拒绝")
        code2, out = self._post("/api/note/save", body, headers={"Origin": "http://127.0.0.1"})
        self.assertEqual(code2, 200, "回环来源写入可用")
        self.assertIn("note_id", out)
        # 幂等：再写同键同内容
        code3, out3 = self._post("/api/note/save", body, headers={"Origin": "http://localhost"})
        self.assertEqual(code3, 200)
        self.assertEqual(json.loads(out3)["revision"], 1)

    def test_dns_rebinding_foreign_host_rejected_on_read(self):
        """DNS rebinding 加固：非回环 Host 的读请求必须拒绝（否则恶意网页可重绑定域名读取索引内容）。"""
        code, _, _ = self._get("/", headers={"Host": "evil.example.com"})
        self.assertEqual(code, 403, "非回环 Host 的 GET 必须拒绝")
        q = urllib.parse.quote("evil-marker 文档")
        code2, _, _ = self._get("/api/search?q=" + q, headers={"Host": "evil.example.com:8080"})
        self.assertEqual(code2, 403, "非回环 Host 的 API 读必须拒绝")
        code3, _, _ = self._get("/", headers={"Host": "127.0.0.1:%d" % self.port})
        self.assertEqual(code3, 200, "回环 Host 正常服务")

if __name__ == "__main__":
    unittest.main()
