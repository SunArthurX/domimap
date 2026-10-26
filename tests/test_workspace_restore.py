"""R07 整库导出恢复（AC-R07-01/03）：证据库+blob+代+图+来源 manifest+知识库作为一个可校验包。

given 运行中的知识库与固定证据 / when 在线备份并在干净目录恢复 / then 正文/修订/审定/范围/引用完整且可检索；
恢复不越界、不覆盖已有目标、坏哈希/缺件拒绝且不留半成品。
"""
import hashlib
import json
import os
import shutil
import tempfile
import unittest

from domimap import workspace
from domimap.graph import Graph, build as graph_build
from domimap.knowledge import KnowledgeStore
from domimap.store import EvidenceStore, EvidenceResolver

HERE = os.path.dirname(os.path.abspath(__file__))
MINI = os.path.join(HERE, "fixtures", "mini")
CLAIMS = [{"type": "decision", "statement": "改价必须带版本号", "evidence": [], "scope": "order-service"}]


class TestWorkspaceExportRestore(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dm-r07-")
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.ws = os.path.join(self.tmp, "out", "mini")
        self.g, _ = graph_build(MINI, self.ws)
        kb = KnowledgeStore(os.path.join(self.ws, "knowledge.db"))
        self.note = kb.submit(body="改价并发结论：乐观锁 + 版本号", claims=CLAIMS, idempotency_key="k-r07")
        kb.amend(self.note["note_id"], "改价并发结论：乐观锁 + 版本号（已复核）", claims=CLAIMS,
                 expected_revision=1)
        kb.close()
        self.archive = os.path.join(self.tmp, "archive")
        self.target = os.path.join(self.tmp, "restored")

    def _doc_ev(self, ws):
        store = EvidenceStore(os.path.join(ws, "store.db"))
        try:
            res = EvidenceResolver(store)
            doc = next(n for n in Graph.load(os.path.join(ws, "graph.json")).nodes.values() if n["kind"] == "Doc")
            ev = res.for_node(doc)
            return ev, store.read_evidence(ev)
        finally:
            store.close()

    def test_export_then_restore_into_clean_dir_keeps_everything(self):
        ev_before, rec_before = self._doc_ev(self.ws)
        manifest = workspace.export_workspace(self.ws, self.archive)
        self.assertEqual(manifest["schema"], "domimap.workspace.v1")
        self.assertIn("store.db", manifest["files"])
        self.assertIn("graph.json", manifest["files"])
        self.assertTrue(any(k.startswith("blobs/") for k in manifest["files"]))
        self.assertTrue(any(k.startswith("gens/") for k in manifest["files"]))
        self.assertTrue(any(k.endswith("/manifest.json") for k in manifest["files"]))
        self.assertTrue(manifest["components"]["knowledge"], "知识库应包含在导出中")
        self.assertFalse(manifest["components"]["queries"], "查询日志默认不导出（隐私）")
        summary = workspace.restore_workspace(self.archive, self.target)
        self.assertTrue(os.path.isdir(self.target))
        # 证据：历史 ev_id 在新目录按同 ID 可读，内容一致
        ev_after, rec_after = self._doc_ev(self.target)
        self.assertEqual(ev_after, ev_before)
        self.assertTrue(rec_after["available"])
        self.assertEqual(rec_after["text"], rec_before["text"])
        # 图：节点集合一致；active 代在新目录可定位（路径不依赖旧绝对路径）
        self.assertEqual(set(Graph.load(os.path.join(self.target, "graph.json")).nodes), set(self.g.nodes))
        store = EvidenceStore(os.path.join(self.target, "store.db"))
        self.addCleanup(store.close)
        self.assertIsNotNone(store.active_generation(), "恢复后 active 代必须可定位（gens 路径按新目录解析）")
        # 知识：正文/修订/审定/范围
        kb = KnowledgeStore(os.path.join(self.target, "knowledge.db"))
        self.addCleanup(kb.close)
        note = kb.get(self.note["note_id"])
        self.assertEqual(note["revision"], 2)
        self.assertIn("已复核", note["body"])
        self.assertEqual(len(kb.history(self.note["note_id"])), 2)
        self.assertEqual(summary["knowledge"]["notes"], 1)
        # 来源 manifest（登记）随包恢复
        labels = [d for d in os.listdir(self.target) if os.path.exists(os.path.join(self.target, d, "manifest.json"))]
        self.assertEqual(len(labels), 1)

    def test_restore_refuses_existing_target_and_leaves_it_untouched(self):
        workspace.export_workspace(self.ws, self.archive)
        os.makedirs(self.target)
        marker = os.path.join(self.target, "keep.txt")
        open(marker, "w").write("mine")
        with self.assertRaises(FileExistsError):
            workspace.restore_workspace(self.archive, self.target)
        self.assertEqual(open(marker).read(), "mine")
        self.assertEqual(os.listdir(self.target), ["keep.txt"])

    def test_restore_rejects_tampered_blob_without_creating_target(self):
        workspace.export_workspace(self.ws, self.archive)
        blob = next(os.path.join(self.archive, "blobs", b) for b in os.listdir(os.path.join(self.archive, "blobs")))
        with open(blob, "ab") as f:
            f.write(b"\n# tampered")
        with self.assertRaisesRegex(ValueError, "sha256"):
            workspace.restore_workspace(self.archive, self.target)
        self.assertFalse(os.path.lexists(self.target), "校验失败不得留下半成品目标")
        self.assertFalse([p for p in os.listdir(self.tmp) if p.startswith(".ws-restore-")], "临时暂存须清理")

    def test_restore_rejects_missing_component(self):
        workspace.export_workspace(self.ws, self.archive)
        os.remove(os.path.join(self.archive, "store.db"))
        with self.assertRaisesRegex(ValueError, "missing"):
            workspace.restore_workspace(self.archive, self.target)
        self.assertFalse(os.path.lexists(self.target))

    def test_restore_rejects_path_traversal_and_symlink_members(self):
        workspace.export_workspace(self.ws, self.archive)
        mp = os.path.join(self.archive, "workspace-manifest.json")
        d = json.load(open(mp, encoding="utf-8"))
        d["files"]["../escape.json"] = "0" * 64
        json.dump(d, open(mp, "w", encoding="utf-8"))
        with self.assertRaisesRegex(ValueError, "path"):
            workspace.restore_workspace(self.archive, self.target)
        self.assertFalse(os.path.lexists(self.target))
        # symlink member
        d["files"].pop("../escape.json")
        json.dump(d, open(mp, "w", encoding="utf-8"))
        gp = os.path.join(self.archive, "graph.json")
        real = gp + ".real"
        os.rename(gp, real)
        os.symlink(real, gp)
        with self.assertRaisesRegex(ValueError, "symlink"):
            workspace.restore_workspace(self.archive, self.target)
        self.assertFalse(os.path.lexists(self.target))

    def test_export_refuses_existing_destination(self):
        os.makedirs(self.archive)
        with self.assertRaises(FileExistsError):
            workspace.export_workspace(self.ws, self.archive)

    def test_queries_db_only_with_explicit_opt_in(self):
        from domimap.observation import run_query
        from domimap.search import Searcher
        s = Searcher(self.g)
        os.environ.pop("DOMIMAP_OBSERVE", None)
        run_query(os.path.join(self.ws, "graph.json"), s, "改价", "cli", {"top_k": 3})
        self.assertTrue(os.path.exists(os.path.join(self.ws, "queries.db")))
        m1 = workspace.export_workspace(self.ws, self.archive)
        self.assertFalse(m1["components"]["queries"])
        self.assertFalse(any(k.startswith("queries.db") for k in m1["files"]))
        m2 = workspace.export_workspace(self.ws, self.archive + "2", include_queries=True)
        self.assertTrue(m2["components"]["queries"])
        self.assertIn("queries.db", m2["files"])
        self.assertTrue(m2.get("contains_query_log"), "含查询日志的包须显式标注，勿公开发布")


class TestWorkspaceCli(unittest.TestCase):
    def test_cli_roundtrip_and_error_codes(self):
        import subprocess, sys
        tmp = tempfile.TemporaryDirectory(prefix="dm-r07-cli-")
        self.addCleanup(tmp.cleanup)
        ws = os.path.join(tmp.name, "ws")
        graph_build(MINI, ws)
        root = os.path.dirname(HERE)
        run = lambda *a: subprocess.run([sys.executable, "-B", "-m", "domimap", *a], cwd=root,
                                        capture_output=True, text=True)
        arch = os.path.join(tmp.name, "arch")
        p = run("export-workspace", ws, arch)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertNotIn("含查询日志", p.stdout)
        self.assertEqual(run("export-workspace", ws, arch).returncode, 4, "目标已存在 → exit 4")
        tgt = os.path.join(tmp.name, "restored")
        p = run("restore-workspace", arch, tgt)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue(os.path.exists(os.path.join(tgt, "store.db")))
        self.assertEqual(run("restore-workspace", arch, tgt).returncode, 4, "目标已存在 → exit 4")
        os.remove(os.path.join(arch, "graph.json"))
        p = run("restore-workspace", arch, tgt + "2")
        self.assertEqual(p.returncode, 5, "缺件 → exit 5")
        self.assertFalse(os.path.lexists(tgt + "2"))


if __name__ == "__main__":
    unittest.main()
