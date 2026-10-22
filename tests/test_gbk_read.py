"""GBK 源码读取回退契约（product-gbk-read）。

实况：企业 Dao 仓文件 GBK 编码，utf-8 宽容读使中文注释乱码、注释桥失效。
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from domimap import lite_scan  # noqa: E402

GBK_JAVA = ("package com.example.pop.dao.delivery;\n\n"
            "/**\n * 设施批量限购区域任务 处理 DAO\n * @author 张三\n */\n"
            "public interface LimitRegionTaskDao {\n}\n").encode("gbk")


class TestGbkRead(unittest.TestCase):
    def _scan(self, files):
        base = tempfile.mkdtemp(prefix="dm-gbk-")
        for rel, blob in files.items():
            path = os.path.join(base, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "wb").write(blob)
        return lite_scan.scan_repo(base), base

    def test_gbk_comment_searchable(self):
        R, _ = self._scan({"src/LimitRegionTaskDao.java": GBK_JAVA})
        self.assertTrue(R["classes"])
        self.assertIn("限购区域任务", R["classes"][0]["comment"],
                      "GBK 注释应可读")
        from domimap.graph import Graph, load_seeds
        from domimap.search import Searcher
        g = Graph()
        g.build_from_records(R, load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
        r = Searcher(g).query("限购区域任务 处理 DAO", top_k=5)
        files = [n.get("file") for n in r.get("seeds", [])]
        self.assertTrue(any("LimitRegionTaskDao" in (f or "") for f in files))

    def test_utf8_still_primary(self):
        R, _ = self._scan({"src/U.java":
                           "public class Util {\n".encode("utf-8")})
        self.assertEqual(R["classes"][0]["name"], "Util")

    def test_binary_garbage_no_crash_no_fake_cjk(self):
        blob = bytes(range(256)) * 4
        R, _ = self._scan({"bin/blob.dat" if False else "src/x.java": blob})
        self.assertEqual(R["classes"], [])


if __name__ == "__main__":
    unittest.main()
