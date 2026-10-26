"""R05/R07 知识层写入口：CLI note/kb、MCP kg_note（门控）、撤回/审定存在性、导入冲突预览、导出页回灌防护。

此前（漂移审计 §2.3）：amend/withdraw/accept/history/backup/restore/export/import 只有库函数（UI 仅 submit，CLI/MCP 无）；
withdraw/accept 对不存在 ID 静默成功；无冲突预览；导出目录可被当普通文档摄入为"新证据"。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from domimap import batch, mcp
from domimap.graph import build as graph_build
from domimap.knowledge import KnowledgeStore, ConflictError

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MINI = os.path.join(HERE, "fixtures", "mini")
CLAIMS = [{"type": "decision", "statement": "改价必须带版本号", "evidence": [], "scope": "order"}]


def run(*a):
    return subprocess.run([sys.executable, "-B", "-m", "domimap", *a], cwd=ROOT, capture_output=True, text=True)


class TestKnowledgeEntries(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dm-kn-")
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.ws = os.path.join(self.tmp, "ws")
        graph_build(MINI, self.ws)
        self.gp = os.path.join(self.ws, "graph.json")
        self.kb_path = os.path.join(self.ws, "knowledge.db")

    def test_withdraw_and_accept_refuse_unknown_targets(self):
        kb = KnowledgeStore(self.kb_path)
        self.addCleanup(kb.close)
        with self.assertRaises(ConflictError):
            kb.withdraw("kn:nope")
        with self.assertRaises(ConflictError):
            kb.accept_claim("kn:nope", 0)
        r = kb.submit("结论 A", claims=CLAIMS, idempotency_key="k1")
        with self.assertRaises(ConflictError):
            kb.accept_claim(r["note_id"], 5)
        self.assertEqual(kb.accept_claim(r["note_id"], 0)["state"], "accepted")
        self.assertEqual(kb.withdraw(r["note_id"])["status"], "withdrawn")
        with self.assertRaises(ConflictError):
            kb.withdraw(r["note_id"])  # 二次撤回不静默

    def test_import_preview_shows_conflict_before_commit(self):
        kb = KnowledgeStore(self.kb_path)
        self.addCleanup(kb.close)
        r = kb.submit("结论 A", claims=CLAIMS, idempotency_key="k1")
        out = os.path.join(self.tmp, "export")
        paths = kb.export_markdown(out)
        path = paths[0]
        text = open(path, encoding="utf-8").read().replace("结论 A", "结论 A（外部编辑）")
        open(path, "w", encoding="utf-8").write(text)
        pv = kb.preview_import(path)
        self.assertEqual(pv["note_id"], r["note_id"])
        self.assertFalse(pv["conflict"])
        self.assertEqual(pv["revisions_ahead"], 0)
        self.assertIn("外部编辑", pv["file_body"]); self.assertEqual(pv["current_body"], "结论 A")
        kb.amend(r["note_id"], "结论 A（库内先改）", expected_revision=1, claims=CLAIMS)
        pv2 = kb.preview_import(path)
        self.assertTrue(pv2["conflict"]); self.assertEqual(pv2["revisions_ahead"], 1)
        self.assertEqual(pv2["current_body"], "结论 A（库内先改）")
        with self.assertRaises(ConflictError):
            kb.import_markdown(path)
        shutil.rmtree(out)
        path2 = kb.export_markdown(out)[0]
        t2 = open(path2, encoding="utf-8").read()
        open(path2, "w", encoding="utf-8").write(t2 + "\n再编辑")
        self.assertEqual(kb.import_markdown(path2)["revision"], 3)

    def test_exported_notes_are_not_reingested_as_evidence(self):
        kb = KnowledgeStore(self.kb_path)
        kb.submit("结论 A", claims=CLAIMS, idempotency_key="k1")
        repo = os.path.join(self.tmp, "repo")
        shutil.copytree(MINI, repo)
        kb.export_markdown(os.path.join(repo, "docs", "kb-export"))
        kb.close()
        ws2 = os.path.join(self.tmp, "ws2")
        g, cov = graph_build(repo, ws2)
        self.assertFalse(any("kb-export" in n["file"] for n in g.nodes.values()),
                         "导出页不得回灌为独立文档节点")
        hit = [s for s in cov["skipped"] if "kb-export" in s["file"]]
        self.assertTrue(hit and "回灌" in hit[0]["reason"], cov["skipped"])
        from domimap.store import EvidenceStore
        st = EvidenceStore(os.path.join(ws2, "store.db"))
        try:
            self.assertEqual(st.db.execute("SELECT COUNT(*) FROM sources WHERE rel LIKE '%kb-export%'").fetchone()[0], 0,
                             "导出页也不固化为证据")
        finally:
            st.close()

    def test_cli_note_lifecycle(self):
        p = run("note", "submit", "--body", "结论 A", "--claims", json.dumps(CLAIMS, ensure_ascii=False),
                "--idempotency-key", "k1", "-g", self.gp)
        self.assertEqual(p.returncode, 0, p.stderr)
        nid = json.loads(p.stdout)["note_id"]
        p = run("note", "amend", nid, "--body", "结论 A v2", "--expected-revision", "1", "-g", self.gp)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["revision"], 2)
        p = run("note", "amend", nid, "--body", "x", "--expected-revision", "1", "-g", self.gp)
        self.assertEqual(p.returncode, 5, "过期修订号 → 冲突 exit 5")
        p = run("note", "history", nid, "-g", self.gp)
        self.assertEqual(len(json.loads(p.stdout)), 2)
        p = run("note", "accept", nid, "--idx", "0", "-g", self.gp)
        self.assertEqual(p.returncode, 0, p.stderr)
        p = run("note", "get", nid, "-g", self.gp)
        self.assertEqual(json.loads(p.stdout)["claims"][0]["state"], "accepted")
        p = run("note", "withdraw", nid, "-g", self.gp)
        self.assertEqual(p.returncode, 0, p.stderr)
        p = run("note", "withdraw", nid, "-g", self.gp)
        self.assertEqual(p.returncode, 5)
        p = run("note", "get", "kn:nope", "-g", self.gp)
        self.assertEqual(p.returncode, 4)

    def test_cli_kb_export_import_backup_restore(self):
        kb = KnowledgeStore(self.kb_path)
        r = kb.submit("结论 A", claims=CLAIMS, idempotency_key="k1"); kb.close()
        out = os.path.join(self.tmp, "md")
        p = run("kb", "export", out, "-g", self.gp)
        self.assertEqual(p.returncode, 0, p.stderr)
        path = os.path.join(out, os.listdir(out)[0])
        t = open(path, encoding="utf-8").read()
        open(path, "w", encoding="utf-8").write(t + "\n外部补充")
        p = run("kb", "import", path, "--preview", "-g", self.gp)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('"conflict": false', p.stdout)
        p = run("kb", "import", path, "-g", self.gp)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["revision"], 2)
        bak = os.path.join(self.tmp, "kb-bak")
        p = run("kb", "backup", bak, "-g", self.gp)
        self.assertEqual(p.returncode, 0, p.stderr)
        dest = os.path.join(self.tmp, "restored.db")
        p = run("kb", "restore", bak, dest, "-g", self.gp)
        self.assertEqual(p.returncode, 0, p.stderr)
        k2 = KnowledgeStore(dest)
        try:
            self.assertEqual(k2.get(r["note_id"])["revision"], 2)
        finally:
            k2.close()
        self.assertEqual(run("kb", "restore", bak, dest, "-g", self.gp).returncode, 4, "已存在目标拒绝")

    def test_mcp_kg_note_is_write_gated_and_conflict_aware(self):
        closed = mcp.Server(self.gp).call("kg_note", {"action": "submit", "body": "x"})
        self.assertTrue(closed["isError"]); self.assertIn("write_disabled", closed["content"][0]["text"])
        srv = mcp.Server(self.gp, enable_write=True)
        names = {t["name"] for t in mcp.visible_tools(True)}
        self.assertIn("kg_note", names)
        out = srv.call("kg_note", {"action": "submit", "body": "结论 A",
                                   "claims": json.dumps(CLAIMS, ensure_ascii=False), "idempotency_key": "k1"})
        self.assertFalse(out["isError"], out)
        nid = json.loads(out["content"][0]["text"])["note_id"]
        out = srv.call("kg_note", {"action": "amend", "note_id": nid, "body": "结论 A v2", "expected_revision": 1})
        self.assertEqual(json.loads(out["content"][0]["text"])["revision"], 2)
        out = srv.call("kg_note", {"action": "amend", "note_id": nid, "body": "x", "expected_revision": 1})
        self.assertIn("error", json.loads(out["content"][0]["text"]), "冲突以结构化错误返回")
        self.assertTrue(srv.call("kg_note", {"action": "destroy"})["isError"], "枚举外动作被 schema 拒绝")
        out = srv.call("kg_note", {"action": "withdraw", "note_id": nid})
        self.assertEqual(json.loads(out["content"][0]["text"])["status"], "withdrawn")
        out = srv.call("kg_note", {"action": "submit", "body": "推断：可能有并发问题",
                                   "claims": json.dumps([{"type": "inference", "statement": "可能有并发问题", "evidence": []}])})
        self.assertFalse(out["isError"])
        kb = KnowledgeStore(self.kb_path)
        try:
            note = kb.get(json.loads(out["content"][0]["text"])["note_id"])
            self.assertEqual(note["claims"][0]["state"], "proposed", "MCP 提交的陈述只是 proposed，不自动 accepted")
        finally:
            kb.close()


if __name__ == "__main__":
    unittest.main()
