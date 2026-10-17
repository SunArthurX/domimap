"""内容纪元契约（product-content-era）。

确认侧硬前置：27 个公共仓 depth-1 克隆的文件 mtime 全为克隆时刻——文档自述日期
是唯一可靠纪元。
"""
import calendar
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from domimap import lite_scan  # noqa: E402


def scan_files(files, mtimes=None):
    base = tempfile.mkdtemp(prefix="dm-era-")
    for rel, content in files.items():
        path = os.path.join(base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write(content)
        if mtimes and rel in mtimes:
            os.utime(path, (mtimes[rel], mtimes[rel]))
    return lite_scan.scan_repo(base), base


class TestContentEra(unittest.TestCase):
    def test_content_date_beats_clone_mtime(self):
        doc = ("# 接口设计文档\n\n发布日期：2017-06-10。\n" + "正文细节内容。\n" * 40)
        R, _ = scan_files({"doc/api.md": doc}, {"doc/api.md": time.time()})
        d = R["docs"][0]
        self.assertIsNotNone(d["content_era"])
        self.assertEqual(time.strftime("%Y-%m-%d", time.gmtime(d["content_era"])),
                         "2017-06-10")
        # 图节点 first_seen 用内容纪元
        from domimap.graph import Graph, load_seeds
        g = Graph()
        g.build_from_records(R, load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
        node = next(n for n in g.nodes.values() if n["kind"] == "Doc")
        self.assertEqual(node["meta"]["era_source"], "content")
        self.assertEqual(node["meta"]["first_seen"], d["content_era"])

    def test_no_date_falls_back_to_mtime(self):
        R, _ = scan_files({"doc/plain.md": "# 无日期\n正文。\n" * 30})
        d = R["docs"][0]
        self.assertIsNone(d["content_era"])
        from domimap.graph import Graph, load_seeds
        g = Graph()
        g.build_from_records(R, load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
        node = next(n for n in g.nodes.values() if n["kind"] == "Doc")
        self.assertEqual(node["meta"]["era_source"], "mtime")

    def test_latest_of_multiple_dates(self):
        doc = ("# 说明\n\n旧规则 2015-11-11。规则更新于 2017/08/21，旧版替代。\n"
               + "细节。\n" * 30)
        R, _ = scan_files({"doc/multi.md": doc})
        era = R["docs"][0]["content_era"]
        self.assertEqual(time.strftime("%Y-%m-%d", time.gmtime(era)), "2017-08-21")

    def test_invalid_dates_rejected(self):
        doc = "# 说明\n\n日期 9999-99-99 与 1800-01-01。\n" + "细节。\n" * 30
        R, _ = scan_files({"doc/bad.md": doc})
        self.assertIsNone(R["docs"][0]["content_era"])

    def test_touch_does_not_change_content_era(self):
        doc = "# 说明\n\n发布日期 2016-03-01。\n" + "细节。\n" * 30
        R, base = scan_files({"doc/t.md": doc})
        before = R["docs"][0]["content_era"]
        os.utime(os.path.join(base, "doc/t.md"), (time.time() + 999, time.time() + 999))
        R2, _2 = scan_files({"doc/t.md": doc})  # 重扫同内容
        self.assertEqual(R2["docs"][0]["content_era"], before)


if __name__ == "__main__":
    unittest.main()
