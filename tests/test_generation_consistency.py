"""RV01 回归（AC-R02-01 / AC-R03-01/02）：图、证据、来源清单组成同一代；发布中断不混用、不误报 no-op。

复现自 out/agent-review-2026-10-27/generation-reproductions.json 的两个中断反例。
"""
import os
import shutil
import tempfile
import unittest

from domimap import batch
from domimap.graph import Graph, build as graph_build
from domimap.service import AppService
from domimap.store import EvidenceStore, EvidenceResolver

V1 = "# Approval policy\n\nVERSION_ONE: approval is required.\n"
V2 = "# Approval policy\n\nVERSION_TWO: approval is forbidden.\n"


def _repo(tmp, text):
    repo = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(repo, "docs"))
    open(os.path.join(repo, "pom.xml"), "w").write("<project/>")
    with open(os.path.join(repo, "docs", "policy.md"), "w", encoding="utf-8") as f:
        f.write(text)
    return repo


def _policy_state(ws):
    """用户可观察状态：图中文本 vs 节点解析到的证据文本。"""
    g = Graph.load(os.path.join(ws, "graph.json"))
    node = next(n for n in g.nodes.values() if n["file"].endswith("policy.md"))
    graph_text = node["meta"]["text"]
    ev_id = EvidenceResolver.beside(os.path.join(ws, "graph.json")).for_node(node)
    store = EvidenceStore(os.path.join(ws, "store.db"))
    try:
        ev = store.read_evidence(ev_id)
        return graph_text, ev["text"], ev_id
    finally:
        store.close()


class TestGenerationConsistency(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dm-rv01-")
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.repo = _repo(self.tmp, V1)
        self.ws = os.path.join(self.tmp, "ws")
        g, _ = graph_build(self.repo, self.ws)
        self.assertEqual(_policy_state(self.ws)[0], V1)

    def _bump_to_v2(self):
        with open(os.path.join(self.repo, "docs", "policy.md"), "w", encoding="utf-8") as f:
            f.write(V2)

    def test_interrupted_before_publication_keeps_consistent_and_rebuilds(self):
        """反例 A：发布前中断——旧图不得引用未发布的新证据；下一次 update 不得 no-op。"""
        self._bump_to_v2()
        original = batch.publish_generation
        try:
            batch.publish_generation = lambda *a, **k: (_ for _ in ()).throw(OSError("injected: before publication"))
            self.assertRaises(OSError, batch.update, self.ws)
        finally:
            batch.publish_generation = original
        graph_text, evidence_text, _ = _policy_state(self.ws)
        self.assertEqual(graph_text, V1, "中断后图仍为已发布的 v1")
        self.assertEqual(evidence_text, V1, "图节点解析到的证据必须与图同代（v1），不得被提前捕获的 v2 背书")
        g, _, results = batch.update(self.ws)
        self.assertIsNotNone(g, "发布前中断后，下一次 update 必须重建，不得把未发布内容当作已完成")
        self.assertEqual([st for _, st in results], ["rebuild"])
        graph_text, evidence_text, _ = _policy_state(self.ws)
        self.assertEqual((graph_text, evidence_text), (V2, V2), "重建后图与证据一致为 v2")

    def test_interrupted_before_compat_copy_serves_old_generation_consistently(self):
        """反例 B：切代后、graph.json 落盘前中断——按图所属代解析，旧版一致服务；下次 update 重建。"""
        self._bump_to_v2()
        original = batch._publish_compat_copy

        def boom(gen_path, json_path):
            raise OSError("injected: before compat copy")

        batch._publish_compat_copy = boom
        try:
            self.assertRaises(OSError, batch.update, self.ws)
        finally:
            batch._publish_compat_copy = original
        graph_text, evidence_text, _ = _policy_state(self.ws)
        self.assertEqual((graph_text, evidence_text), (V1, V1),
                         "兼容副本未落盘时必须一致地服务旧代，不得混用新代证据")
        g, _, results = batch.update(self.ws)
        self.assertIsNotNone(g)
        self.assertEqual([st for _, st in results], ["rebuild"])
        self.assertEqual(_policy_state(self.ws)[:2], (V2, V2))

    def test_service_resolution_is_bound_to_served_graph(self):
        """请求固定版本：AppService 的证据解析绑定其服务的 graph.json 所属代。"""
        self._bump_to_v2()
        original = batch.publish_generation
        try:
            batch.publish_generation = lambda *a, **k: (_ for _ in ()).throw(OSError("injected"))
            self.assertRaises(OSError, batch.update, self.ws)
        finally:
            batch.publish_generation = original
        svc = AppService(os.path.join(self.ws, "graph.json"))
        node = next(n for n in svc.g.nodes.values() if n["file"].endswith("policy.md"))
        ev = svc.read_evidence(svc.evidence_for(node))
        self.assertEqual(node["meta"]["text"], ev["text"], "服务入口：图与证据同代")

    def test_generation_carries_source_version_map(self):
        store = EvidenceStore(os.path.join(self.ws, "store.db"))
        try:
            active = store.active_generation()
            with open(active["path"], encoding="utf-8") as f:
                gen = __import__("json").load(f)
            sources = gen.get("meta", {}).get("sources") or {}
            self.assertTrue(any(s["rel"].endswith("policy.md") for s in sources.values()),
                            "代必须携带其来源版本映射（sid → rel/sha/ev_id）")
            sids = {n["meta"].get("sid") for n in Graph.load(os.path.join(self.ws, "graph.json")).nodes.values()
                    if n["meta"].get("sid")}
            self.assertTrue(sids <= set(sources), "图内每个 sid 都应属于当前代的来源映射")
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
