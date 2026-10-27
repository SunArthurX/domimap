"""T15 卫生批处理：计数文案、scenario 共享扩展、gitignore、导出勿发布提示、DB user_version、doctor DB 检查、
GBK 证据读回、Actions SHA 钉扎与 CI 3.9 矩阵、CHANGELOG 重复标题。
"""
import json
import os
import re
import subprocess
import sqlite3
import sys
import tempfile
import unittest

from domimap.graph import Graph, build as graph_build
from domimap.store import EvidenceStore

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MINI = os.path.join(HERE, "fixtures", "mini")


class TestHygiene(unittest.TestCase):
    def test_ui_docstring_counts_match_workflow_table(self):
        src = open(os.path.join(ROOT, "domimap", "ui.py"), encoding="utf-8").read()
        run, cli = src.count('mode:"run"'), src.count('mode:"cli"')
        self.assertIn("工作台可直接运行 %d 条 + 终端命令 %d 条" % (run, cli), src.split('"""')[1],
                      "docstring 的工作流计数必须与 WORKFLOWS 表一致")

    def test_scenario_req_uses_shared_seed_expansion(self):
        from domimap import scenario
        from domimap.graph import load_seeds
        from domimap.search import Searcher
        g = Graph(); g.add_node("doc:(root):d.md", "Doc", "d.md", "d.md", {"text": "订单 改价 并发"})
        s = Searcher(g)
        seen = {}
        orig = Searcher.query

        def spy(self_, text, **kw):
            seen["text"], seen["kw"] = text, kw
            return orig(self_, text, **kw)

        Searcher.query = spy
        try:
            scenario.scenario_req(g, s, "订单改价 防并发", load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
        finally:
            Searcher.query = orig
        self.assertEqual(seen["text"], "订单改价 防并发", "不再手工把扩展词拼进查询文本")
        self.assertIn("seeds", seen["kw"], "经 Searcher 的 seeds 扩展（含扩展词降权）")

    def test_gitignore_covers_query_logs_globally(self):
        gi = open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()
        for pat in ("queries.db", "queries.db-*", "queries.key"):
            self.assertIn(pat, gi, pat)

    def test_user_version_stamped_and_newer_db_refused(self):
        tmp = tempfile.TemporaryDirectory(prefix="dm-uv-"); self.addCleanup(tmp.cleanup)
        ws = os.path.join(tmp.name, "ws"); graph_build(MINI, ws)
        from domimap.knowledge import KnowledgeStore
        from domimap.observation import ObservationStore
        from domimap import store as _store, knowledge as _kn, observation as _obs
        kb = KnowledgeStore(os.path.join(ws, "knowledge.db")); kb.close()
        obs = ObservationStore(os.path.join(ws, "queries.db")); obs.close()
        for name, expected in (("store.db", _store.USER_VERSION), ("knowledge.db", _kn.USER_VERSION),
                               ("queries.db", _obs.USER_VERSION)):
            p = os.path.join(ws, name)
            if not os.path.exists(p):
                continue
            db = sqlite3.connect(p)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], expected, name)
            db.execute("PRAGMA user_version=%d" % (expected + 1)); db.commit(); db.close()
        with self.assertRaisesRegex(ValueError, "newer"):
            EvidenceStore(os.path.join(ws, "store.db"))
        with self.assertRaisesRegex(ValueError, "newer"):
            KnowledgeStore(os.path.join(ws, "knowledge.db"))

    def test_doctor_reports_database_health(self):
        tmp = tempfile.TemporaryDirectory(prefix="dm-doc-"); self.addCleanup(tmp.cleanup)
        ws = os.path.join(tmp.name, "ws"); graph_build(MINI, ws)
        p = subprocess.run([sys.executable, "-B", "-m", "domimap", "doctor", "-g", os.path.join(ws, "graph.json")],
                           cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("store.db", p.stdout); self.assertIn("quick_check", p.stdout); self.assertIn("user_version", p.stdout)
        self.assertIn("active", p.stdout)

    def test_gbk_evidence_reads_back_as_text(self):
        tmp = tempfile.TemporaryDirectory(prefix="dm-gbk-"); self.addCleanup(tmp.cleanup)
        st = EvidenceStore(os.path.join(tmp.name, "store.db")); self.addCleanup(st.close)
        src = os.path.join(tmp.name, "a.java")
        open(src, "wb").write("// 订单改价：防并发注释\nclass A {}\n".encode("gb18030"))
        rec = st.capture_source("r", "r|a.java", src, "a.java")
        ev = st.read_evidence(rec["ev_id"])
        self.assertIn("订单改价", ev["text"], "GBK 来源的证据读回不得是乱码")
        self.assertNotIn("\ufffd", ev["text"])

    def test_export_warns_when_query_text_present(self):
        tmp = tempfile.TemporaryDirectory(prefix="dm-qx-"); self.addCleanup(tmp.cleanup)
        ws = os.path.join(tmp.name, "ws"); graph_build(MINI, ws)
        gp = os.path.join(ws, "graph.json")
        env = dict(os.environ, DOMIMAP_KEEP_QUERIES="1"); env.pop("DOMIMAP_OBSERVE", None)
        q = subprocess.run([sys.executable, "-B", "-m", "domimap", "query", "订单改价 防并发", "-g", gp],
                           cwd=ROOT, env=env, capture_output=True, text=True)
        qid = re.search(r"(qe:[0-9a-f]+)", q.stderr + q.stdout).group(1)
        fb = subprocess.run([sys.executable, "-B", "-m", "domimap", "feedback", qid, "--relevance", "hit", "-g", gp],
                            cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(fb.returncode, 0, fb.stderr)
        out = os.path.join(tmp.name, "samples.json")
        p = subprocess.run([sys.executable, "-B", "-m", "domimap", "qexport", "-g", gp, "-o", out, "--kind", "success"],
                           cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("勿公开", p.stdout + p.stderr, "导出含查询原文时必须提示勿公开发布")

    def test_actions_pinned_to_sha_and_matrix_covers_floor(self):
        for name in ("ci.yml", "pypi.yml"):
            text = open(os.path.join(ROOT, ".github", "workflows", name), encoding="utf-8").read()
            for m in re.finditer(r"uses:\s*([\w.-]+/[\w.-]+)@([^\s#]+)", text):
                self.assertRegex(m.group(2), r"^[0-9a-f]{40}$", "%s: %s 须钉到提交 SHA" % (name, m.group(1)))
        ci = open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8").read()
        self.assertIn('"3.9"', ci, "requires-python>=3.9 的下限须进 CI 矩阵")

    def test_changelog_has_no_empty_duplicate_heading(self):
        text = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
        self.assertNotRegex(text, r"\n### 已实现\n\n### 已实现")


if __name__ == "__main__":
    unittest.main()
