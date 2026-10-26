"""D10 捕获统一（R02/R03）：普通单仓 build 走证据契约；扫描与证据固化共用同一份字节。

AC-R02-01/02、AC-R03-01 方向：
- `graph.build`（CLI `domimap build <repo>`）产出 store.db + 不可变代 + manifest，候选节点证据可读；
- 每个源文件在一次构建中只从磁盘读取一次（扫描/哈希/片段同源，源在两读之间被改写不再可能）；
- 证据捕获失败进入 coverage.skipped 而不是被吞掉；
- `update` 在普通 build 产物上可用，且沿用构建时记录的服务命名策略（节点 ID 不漂移）。
"""
import builtins
import json
import os
import shutil
import tempfile
import unittest
from collections import Counter

from domimap import batch, lite_scan
from domimap.graph import build as graph_build
from domimap.store import EvidenceStore

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MINI = os.path.join(HERE, "fixtures", "mini")
SEEDS = os.path.join(ROOT, "domimap", "seeds.json")


class TestCaptureUnification(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dm-d10-")
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.out = os.path.join(self.tmp, "out", "mini")

    def test_plain_build_publishes_evidence_contract(self):
        g, cov = graph_build(MINI, self.out, SEEDS)
        self.assertTrue(os.path.exists(os.path.join(self.out, "store.db")), "普通 build 必须固化证据库")
        self.assertTrue(os.path.exists(os.path.join(self.out, "graph.json")))
        store = EvidenceStore(os.path.join(self.out, "store.db"))
        self.addCleanup(store.close)
        self.assertIsNotNone(store.active_generation(), "普通 build 必须发布不可变代")
        # 服务/领域等合成节点的 file 是逻辑名；只对真实来源文件要求证据
        files = {n["file"] for n in g.nodes.values()
                 if n.get("file") and os.path.isfile(os.path.join(MINI, n["file"]))}
        self.assertGreater(len(files), 3)
        ev_map = store.evidence_map()
        missing = sorted(f for f in files if f not in ev_map)
        self.assertEqual(missing, [], "每个有来源文件的节点都应有可读证据")
        for rel in list(files)[:5]:
            ev = store.read_evidence(ev_map[rel])
            self.assertTrue(ev["available"], ev)
        manifests = [p for p in os.listdir(self.out)
                     if os.path.exists(os.path.join(self.out, p, "manifest.json"))]
        self.assertEqual(len(manifests), 1, "单仓 build 也要写 manifest 供 update 增量")

    def test_each_source_file_read_once_per_build(self):
        counter = Counter()
        real_open = builtins.open
        mini_real = os.path.realpath(MINI)

        def counting_open(file, *args, **kwargs):
            try:
                p = os.path.realpath(os.fspath(file))
                if p.startswith(mini_real + os.sep):
                    counter[p] += 1
            except TypeError:
                pass
            return real_open(file, *args, **kwargs)

        builtins.open = counting_open
        try:
            graph_build(MINI, self.out, SEEDS)
        finally:
            builtins.open = real_open
        self.assertTrue(counter, "应读取到夹具文件")
        twice = {p: n for p, n in counter.items() if n > 1}
        self.assertEqual(twice, {}, "扫描与证据捕获必须共用同一次读取（D10）")

    def test_capture_failure_lands_in_coverage(self):
        original = EvidenceStore.capture_source

        def flaky(self_store, repo, sid, abs_path, rel, raw=None):
            if rel.endswith("改价需求PRD.md"):
                raise ValueError("injected blob corruption")
            return original(self_store, repo, sid, abs_path, rel, raw=raw)

        EvidenceStore.capture_source = flaky
        try:
            _, cov = graph_build(MINI, self.out, SEEDS)
        finally:
            EvidenceStore.capture_source = original
        hits = [s for s in cov["skipped"] if s["file"].endswith("改价需求PRD.md")]
        self.assertTrue(hits, "捕获失败必须进入 coverage.skipped，而不是被静默吞掉")
        self.assertIn("证据捕获失败", hits[0]["reason"])

    def test_update_keeps_plain_build_naming(self):
        repo = os.path.join(self.tmp, "mini")
        shutil.copytree(MINI, repo)
        g1, _ = graph_build(repo, self.out, SEEDS)
        ids1 = set(g1.nodes)
        self.assertFalse(any(i.startswith("svc:mini:") for i in ids1),
                         "单仓 build 不以仓名前缀服务（既有命名）")
        g0, _, results0 = batch.update(self.out)
        self.assertIsNone(g0, "无变更应 no-op，而不是 exit 5 的无 manifest")
        self.assertEqual([st for _, st in results0], ["no-op"])
        prd = os.path.join(repo, "docs", "改价需求PRD.md")
        with open(prd, "a", encoding="utf-8") as f:
            f.write("\n\n补充：灰度策略 2026 版。\n")
        g2, _, results = batch.update(self.out)
        self.assertIsNotNone(g2, "源变化后 update 必须重建")
        self.assertEqual([st for _, st in results], ["rebuild"])
        self.assertFalse(any(i.startswith("svc:mini:") for i in g2.nodes),
                         "update 必须沿用 manifest 记录的命名策略，节点 ID 不漂移")
        self.assertEqual({i for i in ids1 if not i.startswith("doc:")},
                         {i for i in g2.nodes if not i.startswith("doc:")})

    def test_discover_build_still_prefixes_services(self):
        roots = batch.discover_roots(os.path.join(HERE, "fixtures"))
        ws = os.path.join(self.tmp, "ws")
        g, _, _ = batch.build_many(roots, ws, force=True, merged_name="fixtures")
        self.assertTrue(any(":" in i.split(":", 1)[1] for i in g.nodes if i.startswith("svc:")),
                        "多仓发现模式保持仓名前缀（既有行为）")
        for root in roots:
            label = os.path.basename(os.path.abspath(root))
            with open(os.path.join(ws, label, "manifest.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f).get("service_prefix"), label)

    def test_scan_decodes_from_captured_bytes(self):
        seen = {}

        def cap(path, rel, raw):
            seen[rel] = raw

        R = lite_scan.scan_repo(MINI, capture=cap)
        self.assertGreater(len(seen), 0)
        self.assertGreaterEqual(len(seen), R["coverage"]["files_scanned"],
                                "捕获覆盖全部遍历文件（含未解析扩展名）")
        prd = next(k for k in seen if k.endswith("改价需求PRD.md"))
        doc = next(d for d in R["docs"] if d["path"] == prd)
        self.assertIn(seen[prd].decode("utf-8").replace("\r\n", "\n")[:40], doc["text"])


if __name__ == "__main__":
    unittest.main()
