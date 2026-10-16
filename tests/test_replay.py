"""历史夹具回放 smoke：原始检索结合场景卡兜底，不代表严格 Top-5 验收。

夹具即"缩小版的真实场景"：mini（订单/商品 + PRD/checklist）+ repo-belt（库存）合并图。
失败时先怀疑检索质量，而不是改期望值——这正是验收闭环存在的目的。
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from domimap import batch, scenario  # noqa: E402
from domimap.graph import load_seeds  # noqa: E402
from domimap.search import Searcher  # noqa: E402

_OUTPUT = tempfile.TemporaryDirectory(prefix="domimap-replay-")
unittest.addModuleCleanup(_OUTPUT.cleanup)
OUT = _OUTPUT.name
SEEDS = load_seeds(os.path.join(ROOT, "domimap", "seeds.json"))

_g = None
def G():
    global _g
    if _g is None:
        roots = batch.discover_roots(os.path.join(HERE, "fixtures"))
        _g, _, _ = batch.build_many(roots, OUT, force=True, merged_name="fixtures")
    return _g

# (查询文本, [Top-5 种子命中的可接受串·任一命中即算命中], 期望领域或 None)
REPLAY_REQ = [
    ("订单改价 防并发",         ["t_order", "price_version", "改价需求PRD"], "订单域"),
    ("price_version 并发控制",  ["price_version", "updatePrice"], None),
    ("order price update 需求", ["t_order", "updatePrice", "changePrice"], "订单域"),
    ("商品 价格同步 监听",       ["PriceSyncListener", "trade-price-changed", "item-service"], "商品域"),
    ("库存预警 消费 重试",       ["stock-warn", "StockWarnConsumer", "ware-service"], "库存域"),
    ("ware_stock 表结构",       ["t_ware_stock", "sku_code", "WareStock"], None),
    ("上线 检查 清单",          ["上线checklist"], None),
    ("rocketmq 发消息 topic",    ["trade-price-changed"], None),
]
REPLAY_REFUSE = ["完全不存在的词zzzqqq", "qwer tyui asdf"]

class TestReplayAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = G()
        cls.s = Searcher(cls.g)

    def _raw_hit(self, text, accepts):
        r = self.s.query(text, top_k=5, expand=False)
        names = " ".join(n["name"] for n in r["seeds"])
        return (not r["refused"]) and any(a in names for a in accepts), names

    def test_raw_hit_rate(self):
        """raw 口径：仅原始 query Top-5 种子命中（不含场景卡兜底）。roadmap 基线 6/8。"""
        hit = 0
        for text, accepts, _dom in REPLAY_REQ:
            ok, names = self._raw_hit(text, accepts)
            hit += ok
            if not ok:
                print("[replay raw MISS] %r -> %s" % (text, names or "REFUSED"))
        rate = hit / len(REPLAY_REQ)
        print("[replay] raw Top-5 命中率 %.0f%% (%d/%d)" % (rate * 100, hit, len(REPLAY_REQ)))
        self.assertGreaterEqual(rate, 0.75, "raw 检索不得低于已登记基线（发现退化先修检索，不改分母）")

    def test_scenario_hit_rate(self):
        """scenario 口径：raw 命中或 scenario req 定位卡（领域词表扩展）命中，独立统计。"""
        hit = 0
        for text, accepts, dom in REPLAY_REQ:
            ok, _names = self._raw_hit(text, accepts)
            if not ok and dom is not None:
                card = scenario.scenario_req(self.g, self.s, text, SEEDS)
                ok = any(a in card for a in accepts)
            hit += ok
        rate = hit / len(REPLAY_REQ)
        print("[replay] scenario 口径命中率 %.0f%% (%d/%d)" % (rate * 100, hit, len(REPLAY_REQ)))
        self.assertGreaterEqual(rate, 0.8)

    def test_refusals(self):
        for text in REPLAY_REFUSE:
            self.assertTrue(self.s.query(text)["refused"], text)

    def test_domain_classify(self):
        for text, _a, dom in REPLAY_REQ:
            if dom:
                self.assertIn(dom, scenario.classify(text, SEEDS), (text, dom))

    def test_scenario_cards(self):
        card = scenario.scenario_req(self.g, self.s, "订单改价 防并发", SEEDS)
        self.assertIn("需求定位卡", card)
        self.assertIn("订单域", card)
        card2 = scenario.scenario_trb(self.g, self.s, "price_version 并发 覆盖")
        self.assertIn("排障卡", card2)

if __name__ == "__main__":
    unittest.main(verbosity=2)
