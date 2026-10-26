"""F4 时间策略（AC-F4-01）：资格先于排序、as_of 三入口可达、时效可解释、touch/复制不刷新。

此前（漂移审计 §2.3/F4 行）：as_of 只存在于库函数（三入口零暴露）；valid_until/superseded_by 资格门槛
只在 as_of 分支内执行（默认查询放行过期/被替代文档）；time_note 计算了从不展示；图平面 first_seen 回退
mtime（touch/复制制造新鲜度，违反 "Copying, touching… does not renew verification"）。
"""
import calendar
import json
import os
import re
import subprocess
import sys
import tempfile
import time as _time
import unittest
import urllib.error
import urllib.request

from domimap import mcp, service
from domimap.graph import Graph, build as graph_build
from domimap.search import Searcher

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _mk_repo(tmp):
    repo = os.path.join(tmp, "timedocs")
    os.makedirs(os.path.join(repo, "docs"))
    open(os.path.join(repo, "pom.xml"), "w").write("<project/>")
    with open(os.path.join(repo, "docs", "expired_spec.md"), "w", encoding="utf-8") as f:
        f.write("---\nvalid_until: 2020-01-01\n---\n# 过期规范\n\n灰度发布规范：2019-03-01 发布，两步灰度。\n")
    with open(os.path.join(repo, "docs", "live_spec.md"), "w", encoding="utf-8") as f:
        f.write("---\nvalid_until: 2099-01-01\n---\n# 现行规范\n\n灰度发布规范：2026-01-15 发布，一步灰度。\n")
    with open(os.path.join(repo, "docs", "old_rule.md"), "w", encoding="utf-8") as f:
        f.write("---\nsuperseded_by: docs/live_spec.md\n---\n# 旧规则\n\n灰度发布旧规则，已被现行规范替代。\n")
    with open(os.path.join(repo, "docs", "undated.md"), "w", encoding="utf-8") as f:
        f.write("# 无日期说明\n\n库存对账口径说明，无任何日期信息。\n")
    return repo


class TestTimePolicy(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dm-f4-")
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.repo = _mk_repo(self.tmp)
        self.ws = os.path.join(self.tmp, "ws")
        self.g, _ = graph_build(self.repo, self.ws)
        self.gp = os.path.join(self.ws, "graph.json")
        os.environ.pop("DOMIMAP_OBSERVE", None)

    def _seed_names(self, r):
        return [n["name"] for n in r["seeds"]]

    def test_default_query_excludes_expired_and_superseded(self):
        s = Searcher(self.g)
        r = s.query("灰度发布 规范", top_k=10)
        names = self._seed_names(r)
        self.assertNotIn("expired_spec.md", names, "默认（当前时间）过期文档不具资格")
        self.assertNotIn("old_rule.md", names, "被替代文档不具资格")
        self.assertIn("live_spec.md", names)

    def test_as_of_resurrects_historical_range(self):
        s = Searcher(self.g)
        past = calendar.timegm(_time.strptime("2019-06-01", "%Y-%m-%d"))
        r = s.query("灰度发布 规范", top_k=10, as_of=past)
        names = self._seed_names(r)
        self.assertIn("expired_spec.md", names, "as_of=2019 时 2020-01 到期的文档仍具资格")
        self.assertNotIn("live_spec.md", names, "晚于 as_of 的现行规范不参与")

    def test_as_of_reachable_from_all_three_entries_with_same_result(self):
        import threading
        from domimap.ui import make_server
        past = calendar.timegm(_time.strptime("2019-06-01", "%Y-%m-%d"))
        # 查询词选取：含原文实词，使 seeds 扩展后仍过覆盖率门（4 文档小夹具）
        # CLI
        p = subprocess.run([sys.executable, "-B", "-m", "domimap", "query", "灰度发布规范 两步灰度",
                            "-g", self.gp, "--as-of", "2019-06-01", "--top", "10"],
                           cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("expired_spec.md", p.stdout)
        self.assertIn("[time:", p.stdout, "文本输出须带时效说明")
        # MCP
        out = mcp.Server(self.gp).call("kg_explore", {"query": "灰度发布规范 两步灰度", "top_k": 10,
                                                      "as_of": past})
        self.assertFalse(out["isError"], out)
        self.assertIn("expired_spec.md", out["content"][0]["text"])
        # UI
        srv = make_server(self.gp, port=0)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown); self.addCleanup(srv.server_close)
        url = ("http://127.0.0.1:%d/api/search?q=%s&as_of=2019-06-01&top_k=10"
               % (port, urllib.request.quote("灰度发布规范 两步灰度")))
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Host": "127.0.0.1"}),
                                    timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        self.assertTrue(any("expired_spec" in n["name"] for n in body["seeds"]), body)
        self.assertTrue(any(n.get("time_note") for n in body["seeds"]), "UI 种子须携带时效说明")
        self.assertTrue(any(n.get("valid_until") for n in body["seeds"] if n["name"] == "expired_spec.md"))

    def test_invalid_as_of_is_a_bounded_error_everywhere(self):
        from domimap.service import parse_as_of, ServiceError
        self.assertIsNone(parse_as_of(None))
        self.assertIsNone(parse_as_of(""))
        self.assertEqual(parse_as_of("2019-06-01"), calendar.timegm(_time.strptime("2019-06-01", "%Y-%m-%d")))
        self.assertEqual(parse_as_of(1_550_000_000), 1_550_000_000.0)
        for bad in ("not-a-date", 99, "2200-13-99", True):
            with self.assertRaises(ServiceError, msg=repr(bad)):
                parse_as_of(bad)
        p = subprocess.run([sys.executable, "-B", "-m", "domimap", "query", "灰度",
                            "-g", self.gp, "--as-of", "someday"],
                           cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("as_of", p.stderr + p.stdout)
        out = mcp.Server(self.gp).call("kg_explore", {"query": "灰度", "as_of": "2019-06-01"})
        self.assertTrue(out["isError"], "MCP schema 只接受 epoch 秒")

    def test_touch_or_copy_does_not_renew_first_seen(self):
        undated = os.path.join(self.repo, "docs", "undated.md")
        node = next(n for n in self.g.nodes.values() if n["name"] == "undated.md")
        self.assertEqual(node["meta"]["era_source"], "store", "无日期文档的纪元来自内容 first_seen 记录")
        fs0 = node["meta"]["first_seen"]
        self.assertGreater(fs0, 0)
        # touch：时间前推一年，内容不变 → first_seen 不得刷新（另改一文件触发重建）
        _time.sleep(0.05)
        future = _time.time() + 366 * 86400
        os.utime(undated, (future, future))
        with open(os.path.join(self.repo, "docs", "live_spec.md"), "a", encoding="utf-8") as f:
            f.write("\n补充：无关改动。\n")
        from domimap import batch
        g2, _, _ = batch.update(self.ws)
        self.assertIsNotNone(g2)
        n2 = next(n for n in g2.nodes.values() if n["name"] == "undated.md")
        self.assertEqual(n2["meta"]["first_seen"], fs0, "touch 不刷新内容首次收录时间")
        # 复制为同内容新文件 → 副本的 first_seen 等于原件（内容历史不因复制重置）
        import shutil
        shutil.copyfile(undated, os.path.join(self.repo, "docs", "undated_copy.md"))
        g3, _, _ = batch.update(self.ws)
        n3 = next(n for n in g3.nodes.values() if n["name"] == "undated_copy.md")
        self.assertEqual(n3["meta"]["first_seen"], fs0, "复制不制造新鲜内容")
        self.assertEqual(n3["meta"]["era_source"], "store")


if __name__ == "__main__":
    unittest.main()
