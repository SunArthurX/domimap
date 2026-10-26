"""D12 原子发布与内容哈希增量（R03）。

AC-R03-01（任一发布阶段中断，读者只见上一完整代或新完整代）、AC-R03-02（图丢失/篡改/同尺寸改写不误报 no-op）。
"""
import hashlib
import json
import os
import shutil
import tempfile
import unittest

from domimap import batch
from domimap.graph import Graph, build as graph_build
from domimap.store import EvidenceStore

HERE = os.path.dirname(os.path.abspath(__file__))
MINI = os.path.join(HERE, "fixtures", "mini")


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class TestAtomicPublish(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dm-d12-")
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.repo = os.path.join(self.tmp, "mini")
        shutil.copytree(MINI, self.repo)
        self.out = os.path.join(self.tmp, "out", "mini")

    def _label(self):
        return [d for d in os.listdir(self.out) if os.path.exists(os.path.join(self.out, d, "manifest.json"))][0]

    def test_manifest_signature_is_content_hash_not_mtime(self):
        graph_build(self.repo, self.out)
        with open(os.path.join(self.out, self._label(), "manifest.json"), encoding="utf-8") as f:
            files = json.load(f)["files"]
        self.assertTrue(files)
        for rel, sig in files.items():
            self.assertIsInstance(sig, str, "签名应为内容哈希字符串，而非 [mtime, size]：%s=%r" % (rel, sig))
            self.assertRegex(sig, r"^[0-9a-f]{64}$")
            self.assertEqual(sig, _sha(os.path.join(self.repo, rel)))

    def test_same_size_rewrite_with_preserved_mtime_is_detected(self):
        graph_build(self.repo, self.out)
        target = os.path.join(self.repo, "docs", "上线checklist.md")
        st = os.stat(target)
        raw = open(target, "rb").read()
        # 同长度改写（翻转最后一个非换行字节），再把 mtime 恢复成原值（cp -p / touch -r 场景）
        idx = len(raw) - 1
        while idx > 0 and raw[idx:idx + 1] in b"\n\r":
            idx -= 1
        flipped = raw[:idx] + (b"X" if raw[idx:idx + 1] != b"X" else b"Y") + raw[idx + 1:]
        with open(target, "wb") as f:
            f.write(flipped)
        os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns))
        self.assertEqual(os.stat(target).st_size, st.st_size)
        self.assertEqual(os.stat(target).st_mtime_ns, st.st_mtime_ns)
        g, _, results = batch.update(self.out)
        self.assertIsNotNone(g, "同尺寸+同 mtime 的内容改写必须被内容哈希识别为变化")
        self.assertEqual([st_ for _, st_ in results], ["rebuild"])
        g0, _, r0 = batch.update(self.out)
        self.assertIsNone(g0)
        self.assertEqual([st_ for _, st_ in r0], ["no-op"])

    def test_graph_json_only_loss_triggers_republish(self):
        g1, _ = graph_build(self.repo, self.out)
        gp = os.path.join(self.out, "graph.json")
        os.remove(gp)
        g2, _, results = batch.update(self.out)
        self.assertIsNotNone(g2, "graph.json 单独丢失不得误报 no-op（D1 残留）")
        self.assertTrue(os.path.exists(gp))
        self.assertEqual(set(g1.nodes), set(Graph.load(gp).nodes))

    def test_graph_json_tamper_or_truncation_triggers_republish(self):
        graph_build(self.repo, self.out)
        gp = os.path.join(self.out, "graph.json")
        store = EvidenceStore(os.path.join(self.out, "store.db"))
        active = store.active_generation()
        store.close()
        with open(gp, "w", encoding="utf-8") as f:
            f.write('{"nodes": [{"id": "x", "kind": "Doc", "name": "x", "file": "x", "meta": {}}], "edges": [], "schema": "domimap.lite.v1"}')
        self.assertNotEqual(_sha(gp), active["sha256"])
        g2, _, results = batch.update(self.out)
        self.assertIsNotNone(g2, "兼容副本与 active 代内容不一致必须重发布")
        self.assertEqual(_sha(gp), EvidenceStore(os.path.join(self.out, "store.db")).active_generation()["sha256"])

    def test_interrupted_compat_publish_keeps_previous_complete_graph(self):
        g1, _ = graph_build(self.repo, self.out)
        gp = os.path.join(self.out, "graph.json")
        before = _sha(gp)
        with open(os.path.join(self.repo, "docs", "上线checklist.md"), "a", encoding="utf-8") as f:
            f.write("\n- 新增项\n")
        original = batch._atomic_write

        def boom(path, data):
            if path.endswith("graph.json"):
                tmp = path + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(data[: len(data) // 2])  # 模拟写到一半崩溃：tmp 残留、目标未切换
                raise OSError("injected crash during compat publish")
            return original(path, data)

        batch._atomic_write = boom
        try:
            with self.assertRaises(OSError):
                batch.update(self.out)
        finally:
            batch._atomic_write = original
        self.assertEqual(_sha(gp), before, "中断时 graph.json 必须仍是上一完整代，不得被截断")
        loaded = Graph.load(gp)
        self.assertEqual(set(loaded.nodes), set(g1.nodes))
        # 恢复后再次 update 必须完成发布并清理临时文件
        g2, _, _ = batch.update(self.out)
        self.assertIsNotNone(g2)
        self.assertFalse([p for p in os.listdir(self.out) if p.endswith(".tmp")], "临时文件须被清理")

    def test_no_tmp_files_left_after_clean_build(self):
        graph_build(self.repo, self.out)
        leftovers = []
        for dp, _, fns in os.walk(self.out):
            leftovers += [os.path.join(dp, fn) for fn in fns if fn.endswith(".tmp")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
