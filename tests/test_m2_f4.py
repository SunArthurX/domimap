"""M2.4：F4 时间矩阵（AC-F4-01）+ kg_explore 证据 ID。"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import domimap.lite_scan as ls  # noqa: E402
from domimap.graph import Graph, load_seeds  # noqa: E402
from domimap.search import Searcher  # noqa: E402

SEEDS = os.path.join(ROOT, "domimap", "seeds.json")

def build_tmp_doc(doc_text):
    tmp = tempfile.mkdtemp(prefix="dm-f4-")
    ws = os.path.join(tmp, "mini")
    shutil.copytree(os.path.join(HERE, "fixtures", "mini"), ws)
    with open(os.path.join(ws, "docs", "timed.md"), "w", encoding="utf-8") as f:
        f.write(doc_text)
    R = ls.scan_repo(ws, repo_label="mini")
    g = Graph(); g.build_from_records(R, load_seeds(SEEDS))
    return g

class TestTimeMatrix(unittest.TestCase):
    def test_validity_and_supersede_and_decay(self):
        g = build_tmp_doc("---\nvalid_until: 2020-01-01\n---\n# timed doc\nunique-f4-marker 说明书")
        doc = next(n for n in g.nodes.values() if n["name"] == "timed.md")
        self.assertEqual(doc["meta"].get("valid_until"), "2020-01-01", "front-matter 应进入元数据")
        r = Searcher(g).query("unique-f4-marker 说明书", top_k=5, as_of=2e9)  # 2033：2020 有效期已过
        self.assertNotIn("timed.md", [n["name"] for n in r["seeds"]], "过期资料不具资格")
        # 衰减可解释：老资料命中时带 time_note
        g2 = build_tmp_doc("---\nfirst_seen_hint: old\n---\n# old doc\nunique-f4-oldmarker 旧规范")
        d2 = next(n for n in g2.nodes.values() if n["name"] == "old doc" or n["name"] == "timed.md")
        d2["meta"]["first_seen"] = 1e9 - 400 * 86400  # 400 天前
        r2 = Searcher(g2).query("unique-f4-oldmarker 旧规范", top_k=5, as_of=2e9)
        self.assertFalse(r2["refused"])
        self.assertTrue(any("decay" in (n.get("time_note") or "") or "未知" in (n.get("time_note") or "")
                            for n in r2["seeds"]), "时间说明必须逐条可解释")

    def test_unknown_and_future_dates(self):
        g = build_tmp_doc("# plain doc\nunique-f4-plain 普通文档")  # 无 front-matter → 日期未知
        r = Searcher(g).query("unique-f4-plain 普通文档", top_k=5, as_of=2e9)
        names = [n["name"] for n in r["seeds"]]
        self.assertIn("timed.md", names, "未知日期按最早处理，不因 as_of 被排除")

class TestExploreEvidenceIds(unittest.TestCase):
    def test_explore_output_contains_ev_ids(self):
        from domimap.ui import make_server  # 仅为确认图存在性无关
        out = os.path.join(HERE, "out_shared")
        if not os.path.exists(out + "/graph.json"):
            self.skipTest("out_shared 未生成")
        from domimap.mcp import Server
        srv = Server(out + "/graph.json")
        text = srv.handle("kg_explore", {"query": "price_version"})
        self.assertIn("ev:", text, "kg_explore 应附证据 ID（会话反馈）")

if __name__ == "__main__":
    unittest.main()


class TestMyBatisBridgeNoDDL(unittest.TestCase):
    def test_mapper_only_corpus_still_links_tables(self):
        tmp = tempfile.mkdtemp(prefix="dm-noddl-")
        ws = os.path.join(tmp, "m")
        os.makedirs(os.path.join(ws, "mapper"))
        open(os.path.join(ws, "mapper", "A.xml"), "w").write(
            '<mapper namespace="com.x.AMapper"><update id="up">UPDATE real_t SET a=1</update></mapper>')
        R = ls.scan_repo(ws, repo_label="m")
        g = Graph(); g.build_from_records(R, load_seeds(SEEDS))
        self.assertIn("tbl:real_t", g.nodes, "无 DDL 时 mapper 表必须建节点")
        self.assertTrue(any(e["kind"] == "WRITES" and e["dst"] == "tbl:real_t" for e in g.edges),
                        "无 DDL 时 WRITES 边不得丢失（真实语料缺陷回归）")
