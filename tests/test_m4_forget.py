"""M4 收尾 R07-03：归档越界/主动遗忘/保留语义。"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from domimap.knowledge import KnowledgeStore  # noqa: E402

def kb_with_note(path, body="遗忘目标 marker-fg"):
    kb = KnowledgeStore(path)
    nid = kb.submit(body=body, claims=[], idempotency_key="fg1")["note_id"]
    return kb, nid

class TestForgetSemantics(unittest.TestCase):
    def test_forget_tombstone_and_backup_explainability(self):
        with tempfile.TemporaryDirectory() as tmp:
            kb, nid = kb_with_note(os.path.join(tmp, "kb.db"))
            bdir = os.path.join(tmp, "b1")
            kb.backup(bdir)                       # 遗忘前备份
            kb.forget(nid, reason="用户要求删除")
            self.assertIsNone(kb.get(nid))
            self.assertFalse(kb.list_active(), "遗忘后检索不可见")
            self.assertEqual(kb.export_markdown(os.path.join(tmp, "md")), [], "导出不含已遗忘")
            self.assertEqual(kb.tombstones()[0]["note_id"], nid, "墓碑可审计")
            # 可解释：遗忘前的备份恢复仍含该笔记（备份时点语义）
            r = KnowledgeStore.restore(bdir, os.path.join(tmp, "r.db"))
            self.assertIsNotNone(r.get(nid), "旧备份恢复仍含（删除不篡改历史备份）")
            # 清理：过期墓碑清除
            kb.purge_expired(retention_days=0)
            self.assertEqual(kb.tombstones(), [])

    def test_purge_hard_deletes_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            kb, nid = kb_with_note(os.path.join(tmp, "kb.db"))
            kb.purge(nid)
            self.assertIsNone(kb.get(nid))
            self.assertEqual(kb.history(nid), [], "硬删含修订（显式操作）")

    def test_restore_rejects_symlinked_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            kb, _ = kb_with_note(os.path.join(tmp, "kb.db"))
            real_dir = os.path.join(tmp, "b")
            kb.backup(real_dir)
            evil = os.path.join(tmp, "evil")
            os.makedirs(evil)
            os.symlink(os.path.join(real_dir, "kb.db"), os.path.join(evil, "kb.db"))
            os.symlink(os.path.join(real_dir, "manifest.json"), os.path.join(evil, "manifest.json"))
            with self.assertRaises(ValueError):
                KnowledgeStore.restore(evil, os.path.join(tmp, "r2.db"))

if __name__ == "__main__":
    unittest.main()
