"""负例拒答守门契约（product-negative-refusal）。

第 5 步诊断实证：no_evidence 负例曾因通用词（规则/配置）命中返回假阳性；
近名标识符+中文词曾绕过纯标识符守门。
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from domimap import lite_scan  # noqa: E402


def build_searcher():
    base = tempfile.mkdtemp(prefix="dm-neg-")
    files = {
        "src/OrderService.java": "/**\n * 订单 改价 处理服务\n */\n"
                                 "public class OrderService {\n"
                                 "    public void changePrice(long id) {}\n}\n",
        "doc/rule.md": "# 规则\n对账流程必须先冻结单据，规则由财务侧维护。\n" + "细节补充\n" * 20,
        "mapper/OrderMapper.xml": "<select>SELECT * FROM t_order_main</select>\n",
    }
    for rel, content in files.items():
        path = os.path.join(base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write(content)
    R = lite_scan.scan_repo(base)
    from domimap.graph import Graph, load_seeds
    from domimap.search import Searcher
    g = Graph()
    g.build_from_records(R, load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
    return Searcher(g)


class TestNegativeRefusal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = build_searcher()

    def test_generic_only_match_refused(self):
        """实质词全缺席、仅通用词命中 → 拒答（原：返回假阳性）。"""
        r = self.s.query("对账差异自动核销 规则 配置", top_k=5)
        self.assertTrue(r.get("refused"), r.get("text"))
        r2 = self.s.query("直播弹幕审核 规则 配置", top_k=5)
        self.assertTrue(r2.get("refused"), r2.get("text"))

    def test_absent_identifier_with_cjk_refused(self):
        """近名/缺席标识符 + 中文词 → 拒答（原：绕过纯标识符守门）。"""
        r = self.s.query("t_order_maiqq 表 定义", top_k=5)
        self.assertTrue(r.get("refused"), r.get("text"))

    def test_present_identifier_unaffected(self):
        r = self.s.query("changePrice 订单 改价 入口", top_k=5)
        self.assertFalse(r.get("refused"))
        files = [n.get("file") for n in r.get("seeds", [])]
        self.assertTrue(any("OrderService" in (f or "") for f in files))

    def test_real_content_words_unaffected(self):
        r = self.s.query("对账 冻结 规则", top_k=5)
        self.assertFalse(r.get("refused"), r.get("text"))

    def test_pure_absent_identifier_still_refused(self):
        r = self.s.query("NoSuchThingAnywhere", top_k=5)
        self.assertTrue(r.get("refused"))


if __name__ == "__main__":
    unittest.main()
