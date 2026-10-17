"""时间衰减意图契约（product-age-decay-intent）。

数值定位：无条件 0.5^(age/365)（半衰期 1 年）把 2015-2017 文档压到 ~0.2%——
gold BM25 74 分仍出不了 top50（dv2-0095/0097/0063）。计划 §10：旧源码精确
符号不因年龄凭空失效。
"""
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from domimap import lite_scan  # noqa: E402


def build(files, mtimes):
    base = tempfile.mkdtemp(prefix="dm-decay-")
    for rel, content in files.items():
        path = os.path.join(base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write(content)
        if rel in mtimes:
            os.utime(path, (mtimes[rel], mtimes[rel]))
    R = lite_scan.scan_repo(base)
    from domimap.graph import Graph, load_seeds
    from domimap.search import Searcher
    g = Graph()
    g.build_from_records(R, load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
    return Searcher(g)


OLD_DOC = ("# 运费模板 计费规则\n\n为指定地区城市设置运费：东城区 丰台区 上海 计费按重量。\n"
           + "运费模板 地区 城市 设置 补充。\n" * 40)
NEW_CODE = ("public class FreightNewUtil {\n"
            "// 运费 地区 城市\n}\n" * 1)


class TestAgeDecayIntent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        nine_years = time.time() - 9 * 365 * 86400
        cls.s = build({"doc/freight.md": OLD_DOC,
                       "src/FreightNewUtil.java": NEW_CODE},
                      {"doc/freight.md": nine_years,
                       "src/FreightNewUtil.java": time.time()})

    def test_non_fresh_query_old_doc_not_crushed_by_age(self):
        r = self.s.query("运费模板 计费规则 地区 城市", top_k=5)
        self.assertFalse(r.get("refused"))
        files = [n["file"] for n in r["seeds"]]
        self.assertEqual(files[0], "doc/freight.md",
                         "非时效查询：高分老文档不得因 9 年年龄被压到新节点之后: %s" % files)

    def test_fresh_query_recency_still_applies(self):
        # 时效意图（含"最新"）：等强匹配下衰减决定顺序——较新文档在前
        nine_years = time.time() - 9 * 365 * 86400
        s2 = build({"doc/old_rule.md": OLD_DOC, "doc/new_rule.md": OLD_DOC},
                   {"doc/old_rule.md": nine_years, "doc/new_rule.md": time.time()})
        r = s2.query("运费模板 最新", top_k=5)
        self.assertFalse(r.get("refused"))
        files = [n["file"] for n in r["seeds"]]
        self.assertEqual(files[0], "doc/new_rule.md",
                         "时效查询等强匹配时应近者先行: %s" % files)

    def test_non_fresh_equal_match_order_not_age_driven(self):
        nine_years = time.time() - 9 * 365 * 86400
        s2 = build({"doc/old_rule.md": OLD_DOC, "doc/new_rule.md": OLD_DOC},
                   {"doc/old_rule.md": nine_years, "doc/new_rule.md": time.time()})
        r = s2.query("运费模板 计费规则", top_k=5)
        self.assertFalse(r.get("refused"))
        self.assertEqual(len(r["seeds"]), 2, "等强匹配非时效查询应两者都在（无年龄压制）")

    def test_time_note_preserved(self):
        r = self.s.query("运费 最新", top_k=5)
        for n in r["seeds"]:
            self.assertIn("time_note", n)


if __name__ == "__main__":
    unittest.main()
