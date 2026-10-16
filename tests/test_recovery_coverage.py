"""M1.4 失效/恢复/coverage 契约：边集等价、扫描中变更、双写者、磁盘满、覆盖缺口枚举。"""
import os
import shutil
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import domimap.lite_scan as lite_scan  # noqa: E402
import domimap.store as store_mod  # noqa: E402
from domimap import batch  # noqa: E402


def tmp_copy_of_fixtures(tag):
    tmp = tempfile.mkdtemp(prefix="dm-m14-")
    ws = os.path.join(tmp, tag)
    shutil.copytree(os.path.join(HERE, "fixtures"), ws)
    return ws


class TestConvergence(unittest.TestCase):
    def test_incremental_equals_full_on_nodes_and_edges(self):
        ws = tmp_copy_of_fixtures("conv")
        roots = batch.discover_roots(ws)
        batch.build_many(roots, os.path.join(ws, "out"), force=True, merged_name="m")
        # 单文件变更：给 OrderController 加一个方法
        p = os.path.join(ws, "mini", "order-service", "src", "main", "java",
                         "com", "example", "trade", "OrderController.java")
        with open(p, "a", encoding="utf-8") as f:
            f.write("\n    public String extraEndpoint() { return \"x\"; }\n")
        g_inc, _, res_inc = batch.build_many(roots, os.path.join(ws, "out"), merged_name="m")
        g_full, _, _ = batch.build_many(roots, os.path.join(ws, "out2"), force=True, merged_name="m")
        self.assertIn("rebuild", [st for _, st in res_inc])
        self.assertEqual(batch.normalized(g_inc), batch.normalized(g_full),
                         "增量与全量的规范化节点集+边集必须等价（AC-R03-02）")


class TestMidScanChange(unittest.TestCase):
    def test_source_modified_during_scan_atomic_view(self):
        ws = tmp_copy_of_fixtures("midscan")
        target = os.path.join(ws, "mini", "docs", "改价需求PRD.md")
        old_sha = None
        import hashlib
        with open(target, "rb") as f:
            old_sha = hashlib.sha256(f.read()).hexdigest()
        new_sha = None
        real_walk = lite_scan._walk
        fired = []

        def walk_with_midscan_change(root, on_skip=None):
            for path, rel in real_walk(root, on_skip):
                if path == target and not fired:
                    fired.append(1)
                    with open(target, "a", encoding="utf-8") as f:
                        f.write("\nmid-scan line")
                    with open(target, "rb") as f:
                        nonlocal new_sha
                        new_sha = hashlib.sha256(f.read()).hexdigest()
                yield path, rel

        lite_scan._walk = walk_with_midscan_change
        try:
            R = lite_scan.scan_repo(os.path.join(ws, "mini"), repo_label="mini")
        finally:
            lite_scan._walk = real_walk
        self.assertTrue(fired, "注入应发生")
        self.assertIsNotNone(new_sha)
        doc = next(d for d in R["docs"] if "改价需求PRD" in d["path"])
        cur_sha = hashlib.sha256(doc["text"].encode("utf-8")).hexdigest()
        self.assertIn(cur_sha, {old_sha, new_sha},
                      "扫描中变更：摄入必须是旧版或新版的原子视图，不得是混合/崩溃")


class TestTwoWriters(unittest.TestCase):
    def test_concurrent_build_many_same_workspace(self):
        ws = tmp_copy_of_fixtures("2w")
        roots = batch.discover_roots(ws)
        out = os.path.join(ws, "out")
        errs = []

        def writer(i):
            try:
                batch.build_many(roots, out, force=True, merged_name="m")
            except Exception as e:  # noqa: BLE001
                errs.append(e)

        ts = [threading.Thread(target=writer, args=(i,)) for i in range(2)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertFalse(errs, errs)
        store = store_mod.EvidenceStore(os.path.join(out, "store.db"))
        act = store.active_generation()
        self.assertIsNotNone(act, "双写者后 active 必须完整")
        import json as _json
        data = _json.load(open(act["path"]))
        self.assertTrue(data["nodes"], "active 代必须有节点（无混代/空代）")
        graph_json = _json.load(open(os.path.join(out, "graph.json")))
        self.assertTrue(graph_json["nodes"])


class TestDiskFull(unittest.TestCase):
    def test_enospc_during_publish_keeps_previous(self):
        tmp = tempfile.mkdtemp(prefix="dm-enospc-")
        store = store_mod.EvidenceStore(os.path.join(tmp, "store.db"))
        from domimap.graph import Graph
        g1 = Graph(); g1.add_node("n1", "Service", "s1", "f"); g1.index()
        store.publish_graph(g1)
        before = store.active_generation()
        real_replace = store_mod.os.replace
        calls = {"n": 0}

        def enospc_once(src, dst):
            if dst.endswith(".json") and calls["n"] == 0:
                calls["n"] += 1
                raise OSError(28, "No space left on device")
            return real_replace(src, dst)

        store_mod.os.replace = enospc_once
        g2 = Graph(); g2.add_node("n2", "Service", "s2", "f"); g2.index()
        try:
            with self.assertRaises(OSError):
                store.publish_graph(g2)
        finally:
            store_mod.os.replace = real_replace
        self.assertEqual(store.active_generation(), before, "磁盘满：active 保持上一完整代")
        store.publish_graph(g2)  # 空间恢复后可继续发布
        self.assertNotEqual(store.active_generation(), before)


class TestCoverageEnumeration(unittest.TestCase):
    def test_gaps_enumerated_with_file_and_reason(self):
        tmp = tempfile.mkdtemp(prefix="dm-cov-")
        ws = os.path.join(tmp, "cov")
        shutil.copytree(os.path.join(HERE, "fixtures", "coverage"), ws)
        big = os.path.join(ws, "huge.java")
        with open(big, "w", encoding="utf-8") as f:
            f.write("// pad\n" * 300000)  # > 2MiB 上限
        R = lite_scan.scan_repo(ws, repo_label="cov")
        reasons = {s["reason"]: s["file"] for s in R["coverage"]["skipped"]}
        self.assertTrue(any("mapper XML 解析失败" in r for r in reasons), reasons)
        self.assertTrue(any(".doc 旧格式" in r for r in reasons), reasons)
        self.assertTrue(any("超过大小上限" in r for r in reasons), reasons)
        self.assertTrue(all(s.get("file") for s in R["coverage"]["skipped"]),
                        "每个缺口必须带 file（不静默跳过）")


if __name__ == "__main__":
    unittest.main()
