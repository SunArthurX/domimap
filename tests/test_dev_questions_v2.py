"""dev 题集 v2 语义契约（comparison-dev-questions-v2）。

锁定修正目标：mtime 无关、正文成题（非标题/文件名）、定位单列、题/gold 分文件、
四因负例带验证、标识符题占比上限、确定性。
"""
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "benchmarks"))

from corpus import generate_questions_v2 as gen  # noqa: E402

CN = re.compile(r"[\u4e00-\u9fff]{2,}")


def fixture(base):
    roots = {}
    famA = os.path.join(base, "famA")
    famB = os.path.join(base, "famB")
    famC = os.path.join(base, "famC")
    for f in (famA, famB, famC):
        os.makedirs(f, exist_ok=True)
    roots["famA"], roots["famB"], roots["famC"] = famA, famB, famC

    def put(root, rel, text):
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write(text)

    # famA：共享表 + 带中文注释类 + 带日期/限制句文档 + README
    put(famA, "sql/order.sql",
        "CREATE TABLE t_order_main (id BIGINT);\n")
    put(famA, "src/OrderMainService.java",
        "/**\n * 订单改价 并发控制 处理服务\n */\npublic class OrderMainService {\n}\n")
    put(famA, "doc/订单说明.md",
        "# 订单说明\n\n订单改价需要审核流程。改价必须审核：单日限额 1000 元，\n"
        "超额订单禁止自动通过。审核规则更新于 2026-01-15，\n"
        "旧规则 2025-06-01 已被替代失效。退货冲销需要人工复核。\n" + "业务细节说明补充。\n" * 30)
    put(famA, "README.md", "# famA\n订单主服务。\n" + "细节\n" * 50)
    # famB：同名共享表 + 同名类（歧义负例） + 较旧日期文档
    put(famB, "mapper/OrderMapper.xml",
        "<select>SELECT * FROM t_order_main WHERE 1=1</select>\n")
    put(famB, "src2/OrderMainService.java",
        "/**\n * 供应商 订单履约 服务\n */\npublic class OrderMainService {\n}\n")
    put(famB, "doc/guide.md",
        "# 履约指南\n\n供应商履约注意事项：发货前必须校验库存。\n"
        "规则发布于 2025-03-01。退货需要拦截。\n" + "履约流程细节。\n" * 40)
    # famC：独立表（错范围负例素材）
    put(famC, "sql/inv.sql", "CREATE TABLE t_inventory_ck (id BIGINT);\n")
    return roots


class TestDevQuestionsV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="dm-qv2-")
        cls.roots = fixture(cls.tmp)
        cls.small_quota = {"code_location": 4, "cross_repo_trace": 2,
                           "document_reasoning": 3, "knowledge_freshness": 2,
                           "locator_diagnostic": 3, "negative": 8}
        cls.questions, cls.gold, cls.counts = cls._generate()

    @classmethod
    def _generate(cls):
        original = dict(gen.QUOTA)
        gen.QUOTA.clear()
        gen.QUOTA.update(cls.small_quota)
        try:
            return gen.build(sorted(cls.roots), root_of=cls.roots.__getitem__)
        finally:
            gen.QUOTA.clear()
            gen.QUOTA.update(original)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _gold(self, qid):
        return next(g for g in self.gold if g["id"] == qid)

    def test_questions_carry_no_gold_fields(self):
        for q in self.questions:
            self.assertEqual(set(q), {"id", "category", "query"})
        ids = [q["id"] for q in self.questions]
        self.assertEqual(len(ids), len(set(ids)))

    def test_mtime_independence(self):
        """负例：touch 全部文件后重新生成，题集必须不变（旧版用 mtime 成题）。"""
        for root in self.roots.values():
            for dirpath, _d, files in os.walk(root):
                for fn in files:
                    os.utime(os.path.join(dirpath, fn), (time.time() + 7, time.time() + 7))
        questions2, gold2, _ = self._generate()
        self.assertEqual(questions2, self.questions)
        self.assertEqual([g["gold_paths"] for g in gold2],
                         [g["gold_paths"] for g in self.gold])

    def test_freshness_gold_uses_in_doc_date(self):
        fresh = [q for q in self.questions if q["category"] == "knowledge_freshness"]
        self.assertTrue(fresh, "缺时效题")
        for q in fresh:
            g = self._gold(q["id"])
            joined = " ".join(g["necessary_facts"])
            self.assertRegex(joined, r"20\d{2}-\d{2}-\d{2}", "时效事实必须含文档内日期")
            for path in g["gold_paths"]:
                rel = path.split("/", 1)[1]
                content = open(os.path.join(self.roots[g["families"][0]], rel),
                               encoding="utf-8").read()
                for d in re.findall(r"20\d{2}-\d{2}-\d{2}", joined):
                    self.assertIn(d.replace("-", "-"), content,
                                  "gold 日期必须来自文档内容")

    def test_doc_reasoning_query_not_title_or_filename(self):
        dr = [q for q in self.questions if q["category"] == "document_reasoning"]
        self.assertTrue(dr)
        for q in dr:
            g = self._gold(q["id"])
            path = g["gold_paths"][0]
            rel = path.split("/", 1)[1]
            stem = os.path.splitext(os.path.basename(rel))[0]
            title = None
            content = open(os.path.join(self.roots[g["families"][0]], rel),
                           encoding="utf-8").read()
            m = re.search(r"^#{1,3}\s+(.+)$", content, re.M)
            if m:
                title = m.group(1).strip()
            for token in CN.findall(q["query"]):
                self.assertNotIn(token, stem, "查询词不得含文件名词")
                if title:
                    self.assertNotIn(token, title, "查询词不得含标题词")

    def test_locator_separate_diagnostic(self):
        loc = [q for q in self.questions if q["category"] == "locator_diagnostic"]
        self.assertTrue(loc)
        for q in loc:
            g = self._gold(q["id"])
            self.assertIn("diagnostic-only", g["verify_method"])
        main4 = {"code_location", "cross_repo_trace", "document_reasoning",
                 "knowledge_freshness"}
        for q in self.questions:
            if q["category"] in main4:
                self.assertNotIn("标题检索", self._gold(q["id"])["verify_method"])

    def test_identifier_query_ratio_capped(self):
        import math
        cl = [q for q in self.questions if q["category"] == "code_location"]
        ident = [q for q in cl if self._gold(q["id"])["verify_method"].startswith("grep")]
        self.assertLessEqual(
            len(ident), math.ceil(self.small_quota["code_location"] * 0.4),
            "标识符串查题不得超过类配额 40%")

    def test_negatives_four_causes_with_verification(self):
        neg = [g for g in self.gold if g["category"] == "negative"]
        causes = {}
        for g in neg:
            cause = g["verify_method"].split("：")[0]
            causes[cause] = causes.get(cause, 0) + 1
            self.assertIn(g["disposition"], ("abstain", "clarify"))
            self.assertEqual(g["gold_paths"], [])
        for cause in ("无证据", "近名", "歧义", "错范围"):
            self.assertIn(cause, causes, "负例缺 %s 因" % cause)

    def test_cross_trace_multi_family_gold(self):
        cross = [g for g in self.gold if g["category"] == "cross_repo_trace"]
        self.assertTrue(cross)
        for g in cross:
            self.assertGreaterEqual(len(g["families"]), 2, "跨仓题 gold 必须 ≥2 族")

    def test_determinism(self):
        questions2, _gold2, _c = self._generate()
        self.assertEqual(questions2, self.questions)

    def test_mock_pages_excluded_from_gold(self):
        """第 5 步诊断回归：mock 页占位文本（谁谁谁/啥啥啥）不得成题或污染查询词。"""
        mockA = os.path.join(self.tmp, "famMock")
        os.makedirs(os.path.join(mockA, "doc"), exist_ok=True)
        open(os.path.join(mockA, "doc", "demo.html"), "w", encoding="utf-8").write(
            "<html><body><p>经销商详情 谁谁谁 谁谁谁 啥啥啥医药有限公司 aaaabbbb "
            "药品批发企业 药品批发企业 药品批发企业 固定电话 注册日期 2015-11-11 "
            "注意：注册信息必须审核。</p></body></html>" + "<p>药品批发企业 固定电话</p>" * 20)
        roots = dict(self.roots)
        roots["famMock"] = mockA
        original = dict(gen.QUOTA)
        gen.QUOTA.clear()
        gen.QUOTA.update({"code_location": 0, "cross_repo_trace": 0,
                          "document_reasoning": 2, "knowledge_freshness": 2,
                          "locator_diagnostic": 2, "negative": 0})
        try:
            questions2, gold2, _c = gen.build(sorted(roots), root_of=roots.__getitem__)
        finally:
            gen.QUOTA.clear()
            gen.QUOTA.update(original)
        for g in gold2:
            self.assertNotIn("famMock", g["families"],
                             "mock 族不得进入 gold: %s" % g["families"])
        for q in questions2:
            self.assertNotIn("谁谁谁", q["query"])
            self.assertNotIn("啥啥啥", q["query"])


if __name__ == "__main__":
    unittest.main()
