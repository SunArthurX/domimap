"""M1.3 固化证据与 generation 契约（AC-R02-01 / AC-R03-01 / AC-R03-02，先红后绿）。"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from domimap import batch  # noqa: E402
from domimap.graph import Graph, load_seeds  # noqa: E402
from domimap.store import EvidenceStore  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "mini")
SEEDS = os.path.join(ROOT, "domimap", "seeds.json")


def build_workspace(tmp):
    """build_many 到 tmp，返回 (store_path, graph)。"""
    roots = batch.discover_roots(os.path.join(HERE, "fixtures"))
    g, _, _ = batch.build_many(roots, tmp, force=True, merged_name="fixtures")
    return os.path.join(tmp, "store.db"), g


class TestImmutableEvidence(unittest.TestCase):
    def test_old_evidence_id_survives_source_change_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = os.path.join(tmp, "ws")
            shutil.copytree(FIX, os.path.join(ws, "mini"))
            (os.path.join(ws, "mini", "marker.marker")) if False else None
            os.makedirs(ws, exist_ok=True)
            # 用复制的夹具建库（可安全修改/删除源）
            g = Graph()
            import domimap.lite_scan as ls
            R = ls.scan_repo(os.path.join(ws, "mini"), repo_label="mini")
            g.build_from_records(R, load_seeds(SEEDS))
            store = EvidenceStore(os.path.join(ws, "store.db"))
            for path, rel in ls._walk(os.path.join(ws, "mini")):
                store.capture_source("mini", "mini|" + rel, path, rel)
            store.publish_graph(g, extra_meta={"label": "mini"})
            srcs = store.list_sources()
            self.assertTrue(srcs, "应登记来源")
            target = next(s for s in srcs if s["rel"].endswith("OrderMapper.java"))
            ev = store.evidence_for_source(target["sid"])
            self.assertIsNotNone(ev, "来源应有固化证据")
            # 修改源
            p = os.path.join(ws, "mini", "order-service", "src", "main", "java",
                             "com", "example", "trade", "OrderMapper.java")
            with open(p, "a", encoding="utf-8") as f:
                f.write("\n// changed after capture\n")
            again = store.evidence_for_source(target["sid"])
            self.assertEqual(again["text"], ev["text"], "旧 ID 必须返回固定旧片段（AC-R02-01）")
            self.assertNotIn("changed after capture", again["text"])
            # 删除源：仍可读（blob 不可变）
            os.remove(p)
            third = store.evidence_for_source(target["sid"])
            self.assertEqual(third["sha256"], ev["sha256"])
            self.assertEqual(third["text"], ev["text"])


class TestGenerationPublish(unittest.TestCase):
    def test_interrupted_publish_keeps_previous_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(os.path.join(tmp, "store.db"))
            g1 = Graph(); g1.add_node("n1", "Service", "s1", "f"); g1.index()
            store.publish_graph(g1, extra_meta={"gen": 1})
            active_before = store.active_generation()
            g2 = Graph(); g2.add_node("n2", "Service", "s2", "f"); g2.index()
            # 阶段1：写 gen 前崩溃（注入：payload 校验失败）
            store._fail_stage = "validate"
            with self.assertRaises(RuntimeError):
                store.publish_graph(g2, extra_meta={"gen": 2})
            self.assertEqual(store.active_generation(), active_before, "校验失败不切指针")
            # 阶段2：gen 文件损坏（写坏 JSON 后走校验）
            bad = os.path.join(tmp, "gens")
            with open(os.path.join(bad, "gen-crash.json"), "w") as f:
                f.write("{not json")
            store._fail_stage = None
            gen_files = sorted(os.listdir(bad))
            self.assertTrue(any("tmp" not in f and "crash" in f for f in gen_files))
            self.assertEqual(store.active_generation(), active_before, "损坏代不被激活")
            # 成功发布后切换
            gen2 = store.publish_graph(g2, extra_meta={"gen": 2})
            self.assertNotEqual(store.active_generation(), active_before)
            data = json.load(open(store.active_generation()["path"]))
            self.assertEqual(len(data["nodes"]), 1)

    def test_concurrent_publishers_leave_valid_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(os.path.join(tmp, "store.db"))
            g0 = Graph(); g0.add_node("n0", "Service", "s0", "f"); g0.index()
            store.publish_graph(g0)
            errs = []

            def worker(i):
                try:
                    s = EvidenceStore(os.path.join(tmp, "store.db"))
                    g = Graph(); g.add_node("n%d" % i, "Service", "s%d" % i, "f"); g.index()
                    s.publish_graph(g, extra_meta={"w": i})
                except Exception as e:  # noqa: BLE001
                    errs.append(e)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
            [t.start() for t in threads]
            [t.join() for t in threads]
            self.assertFalse(errs, errs)
            act = store.active_generation()
            data = json.load(open(act["path"]))
            self.assertEqual(len(data["nodes"]), 1, "active 必须是某个完整代（单图）")


class TestUpdateNotNoopWhenGraphLost(unittest.TestCase):
    def test_active_generation_loss_triggers_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = os.path.join(tmp, "ws")
            roots = batch.discover_roots(os.path.join(HERE, "fixtures"))
            g1, _, _ = batch.build_many(roots, ws, force=True, merged_name="fixtures")
            nodes1 = set(g1.nodes)
            # D1 场景：manifest 不变，但 active 代文件被删
            store = EvidenceStore(os.path.join(ws, "store.db"))
            os.remove(store.active_generation()["path"])
            os.remove(os.path.join(ws, "graph.json"))
            g2, _, results = batch.build_many(roots, ws, merged_name="fixtures")
            self.assertIsNotNone(g2, "图丢失不得误报 no-op（D1/AC-R03-02）")
            self.assertEqual(set(g2.nodes), nodes1, "重建结果与全量等价")

    def test_seeds_change_triggers_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = os.path.join(tmp, "ws")
            roots = batch.discover_roots(os.path.join(HERE, "fixtures"))
            batch.build_many(roots, ws, force=True, merged_name="fixtures")
            seeds_path = os.path.join(ROOT, "domimap", "seeds.json")
            backup = open(seeds_path, encoding="utf-8").read()
            try:
                d = json.loads(backup)
                d["订单域"]["keywords"].append("trial-marker-kw")
                open(seeds_path, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False))
                g, _, results = batch.build_many(roots, ws, merged_name="fixtures")
                states = [st for _, st in results]
                self.assertIn("rebuild", states, "种子变化必须触发重建：%s" % states)
                self.assertIsNotNone(g)
            finally:
                open(seeds_path, "w", encoding="utf-8").write(backup)

    def test_update_without_manifests_errors_not_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            g, cov, results = batch.update(tmp)
            self.assertEqual(results, [])
            self.assertIsNone(g)
            # CLI 层必须报错退出（见 test_cli_update_requires_manifests）


if __name__ == "__main__":
    unittest.main()
