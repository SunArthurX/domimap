"""分路命中再融合契约（product-lane-fusion，用户 2026-10-22 指示）。

核心语义：代码/文档/知识三路各自召回（路内 fam 去重 + 路内断崖），融合时每条非空路
保底入席——巨型泛词文档不再独占结果（旧全局 45% 断崖曾把代码路与 Knowledge 笔记剪光，
见 product-llm-enrich-hardening A/B）。拒答语义与打分不变。
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from domimap import lite_scan  # noqa: E402
from domimap.graph import Graph, load_seeds  # noqa: E402
from domimap.knowledge import KnowledgeStore, LLM_NOTE_PREFIX, attach_if_present  # noqa: E402
from domimap.search import Searcher  # noqa: E402

SEEDS = load_seeds(os.path.join(ROOT, "domimap", "seeds.json"))

DOC_HUGE = "# 接入使用指南\n\n" + "测试环境 说明 限制 条件 接入 方式 。" * 60  # 泛词堆叠的巨型文档
DOC_WEAK = "# 附录\n\n接入 说明 一次。"  # 弱文档：同词仅一次，路内断崖应剪掉
JAVA = """package com.example.trade;

/**
 * 接入 配置 说明
 */
public class AccessConfig {
    public String testEnv() { return "测试环境"; }
}
"""


def build_graph(files):
    ws = tempfile.mkdtemp(prefix="dm-lane-ws-")
    out = tempfile.mkdtemp(prefix="dm-lane-out-")
    for rel, text in files.items():
        path = os.path.join(ws, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write(text)
    g = Graph()
    g.build_from_records(lite_scan.scan_repo(ws), SEEDS)
    graph_path = os.path.join(out, "graph.json")
    g.save(graph_path)
    return graph_path


BASE = {"docs/guide.md": DOC_HUGE, "docs/weak.md": DOC_WEAK,
        "src/AccessConfig.java": JAVA}


def searcher_with(graph_path, notes=()):
    s = Searcher(Graph.load(graph_path))
    if notes:
        kb = KnowledgeStore(os.path.join(os.path.dirname(graph_path), "knowledge.db"))
        for body in notes:
            kb.submit(body, [{"type": "inference", "statement": "s", "evidence": [],
                              "scope": ""}])
        kb.close()
        attach_if_present(s, graph_path)
    return s


LLM_NOTE = (LLM_NOTE_PREFIX + "model=m｜source=docs/guide.md｜text_sha=0123456789abcdef】\n"
            "测试环境 接入 说明：本文描述接入方式与限制条件 test env")


class TestLaneFusion(unittest.TestCase):
    def test_doc_dominant_query_still_returns_code_lane(self):
        """用户核心诉求：文档高分霸榜时，代码路命中不被全局断崖剪光。"""
        s = searcher_with(build_graph(BASE))
        r = s.query("测试环境 说明 限制 条件 接入", top_k=6, seeds=SEEDS)
        kinds = [n["kind"] for n in r["seeds"]]
        self.assertTrue(any(k not in ("Doc", "Knowledge") for k in kinds),
                        "代码路必须有代表：%s" % kinds)
        self.assertTrue(any(k == "Doc" for k in kinds), "文档路在场：%s" % kinds)

    def test_code_dominant_query_keeps_doc_floor(self):
        s = searcher_with(build_graph(BASE))
        r = s.query("AccessConfig testEnv 测试环境 接入", top_k=6, seeds=SEEDS)
        self.assertFalse(r.get("refused"), r["text"][:80])
        kinds = [n["kind"] for n in r["seeds"]]
        self.assertEqual(kinds[0] != "Doc" and kinds[0] != "Knowledge", True,
                         "标识符加权应使代码路居首：%s" % kinds)
        self.assertTrue(any(k not in ("Doc", "Knowledge") for k in kinds), "代码路在场")
        self.assertTrue(any(k == "Doc" for k in kinds), "文档路不饥饿（原 want_docs 语义）")

    def test_knowledge_lane_guaranteed_seat(self):
        """A/B 阻断场景复现：巨型文档霸榜 + 高精度 LLM 笔记 → 笔记保底 1 席。"""
        s = searcher_with(build_graph(BASE), notes=[LLM_NOTE])
        r = s.query("测试环境 说明 限制 条件 接入", top_k=6, seeds=SEEDS)
        kinds = [n["kind"] for n in r["seeds"]]
        self.assertIn("Knowledge", kinds, "Knowledge 路保底入席：%s" % kinds)
        kn = [n for n in r["seeds"] if n["kind"] == "Knowledge"][0]
        self.assertEqual(kn["conf"], "LLM")
        # 三路齐全
        self.assertTrue(any(k not in ("Doc", "Knowledge") for k in kinds), "代码路仍在场")

    def test_per_lane_cliff_prunes_weak_doc_but_keeps_code(self):
        """路内断崖：弱文档（<45% 路内 top）被剪；跨路低分代码仍存活。"""
        s = searcher_with(build_graph(BASE))
        r = s.query("测试环境 说明 限制 条件 接入", top_k=6, seeds=SEEDS)
        files = [n["file"] for n in r["seeds"]]
        self.assertNotIn("docs/weak.md", files, "弱文档应被路内断崖剪掉：%s" % files)
        self.assertIn("docs/guide.md", files)
        self.assertTrue(any(f == "src/AccessConfig.java" for f in files),
                        "低分代码路存活：%s" % files)

    def test_same_file_capped_at_two(self):
        files = {"db/schema.sql": "CREATE TABLE t_price_a (i INT);\n"
                                  "CREATE TABLE t_price_b (i INT);\n"
                                  "CREATE TABLE t_price_c (i INT);\n",
                 "src/A.java": "public class A { /* price */ }"}
        s = searcher_with(build_graph(files))
        r = s.query("price 表 定义", top_k=6, seeds=SEEDS)
        n_sql = sum(1 for n in r["seeds"] if n["file"] == "db/schema.sql")
        self.assertLessEqual(n_sql, 2, "同文件 ≤2 席：%s" % [n["file"] for n in r["seeds"]])

    def test_refusal_semantics_unchanged(self):
        s = searcher_with(build_graph(BASE))
        r = s.query("asdfqwer_zzzz 完全不存在", top_k=6, seeds=SEEDS)
        self.assertTrue(r.get("refused"), "拒答守门不因分路融合而放松")

    def test_citation_integrity_after_fusion(self):
        """AC-R04-02：融合结果逐条带 file 出处与 conf/prov（引用完整）。"""
        s = searcher_with(build_graph(BASE), notes=[LLM_NOTE])
        r = s.query("测试环境 说明 限制 条件 接入", top_k=6, seeds=SEEDS)
        self.assertTrue(r["seeds"])
        for n in r["seeds"]:
            self.assertTrue(n.get("file"), "节点缺出处：%r" % n.get("name"))
            self.assertTrue(n.get("conf") and n.get("prov"))
        self.assertIn("knowledge:note:", "\n".join(n["file"] for n in r["seeds"]))


if __name__ == "__main__":
    unittest.main()
