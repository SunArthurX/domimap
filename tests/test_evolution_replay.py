"""retrieval-evolution-replay（drift-corrected）：可信回放、启用门槛与追溯契约。

F02/F04 纠正后的契约：
- 期望必须绑定精确节点身份（node/nodes）；同文件错误节点=miss；旧子串格式拒绝。
- run 带冻结 manifest（runner/scorer/样本摘要/图与知识代际/词表指纹）；维度不一致
  不可比较；缺 manifest 的旧 run 仅作历史。
- activated 需要现存簇+属于该簇的诊断+三 run manifest 一致+improved+回滚逐样本
  等价且代码指纹相同+候选指纹非 unknown。
- chain 只显示与簇关联的 run。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from domimap import lite_scan as ls  # noqa: E402
from domimap import replay  # noqa: E402
from domimap.graph import Graph, load_seeds  # noqa: E402
from domimap.search import Searcher  # noqa: E402

FP = "fp-test-000000"


def build_workspace(prefix="dm-rp-"):
    tmp = tempfile.mkdtemp(prefix=prefix)
    base = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(base, "docs"))
    for i in range(1, 13):
        with open(os.path.join(base, "docs", "g%02d.md" % i), "w",
                  encoding="utf-8") as f:
            f.write("# 主题材料 %02d\n共享词 内容 独有词%02d\n%s\n"
                    % (i, i, "细节" * (i * 3)))
    R = ls.scan_repo(base)
    g = Graph()
    g.build_from_records(R, load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
    gp = os.path.join(tmp, "graph.json")
    g.save(gp)
    return tmp, gp, Searcher(g)


def write_samples(path, samples):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"samples": samples}, f, ensure_ascii=False, indent=1)
    return path


class TestReplayScoring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dm-rp2-")
        self.gp = os.path.join(self.tmp, "graph.json")
        g = Graph()
        g.add_node("wanted", "Method", "required_rule", "same.java")
        g.add_node("wrong", "Method", "unrelated_rule", "same.java")
        g.save(self.gp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_same_file_wrong_node_is_miss(self):
        # probes.json: same_file_wrong_node——文件级子串曾把同文件错误节点记为命中
        gp = self.gp

        class WrongResult:
            extra = {}

            def __init__(self):
                self.g = Graph.load(gp)
                self.received = []

            def query(self, text, **params):
                self.received.append(params)
                return {"seeds": [self.g.nodes["wrong"]], "expanded": [],
                        "refused": False}
        s = WrongResult()
        run = replay.run_replay(self.gp, s,
                                [{"id": "one", "query": "required_rule",
                                  "expect": {"node": "wanted"}}],
                                "sha-node", "candidate", source_fingerprint=FP)
        self.assertFalse(run["results"][0]["ok"], "同文件错误节点必须是 miss")
        self.assertIsNone(run["results"][0]["rank"])

    def test_optional_layers_explicitly_false(self):
        # probes.json: replay_optional_layers——显式关闭不允许环境回退
        gp = self.gp

        class Recorder:
            extra = {}

            def __init__(self):
                self.g = Graph.load(gp)
                self.received = []

            def query(self, text, **params):
                self.received.append(params)
                return {"seeds": [], "expanded": [], "refused": True}
        s = Recorder()
        replay.run_replay(self.gp, s,
                          [{"id": "r", "query": "x", "expect": "refused"}],
                          "sha-opt", "candidate")
        got = s.received[-1]
        for key in ("semantic", "rerank", "embed"):
            self.assertIs(got.get(key), False,
                          "%s 必须显式 False（不得缺省交给环境开关）" % key)

    def test_legacy_substring_gold_rejected(self):
        p = write_samples(os.path.join(self.tmp, "legacy.json"),
                          [{"id": "l", "query": "x", "expected": "docs/g01.md"}])
        with self.assertRaises(ValueError) as cm:
            replay.load_samples(p)
        self.assertIn("废弃", str(cm.exception))

    def test_group_of_nodes_accepted(self):
        gp = self.gp

        class Either:
            extra = {}

            def __init__(self):
                self.g = Graph.load(gp)

            def query(self, text, **params):
                return {"seeds": [self.g.nodes["wrong"]], "expanded": [],
                        "refused": False}
        run = replay.run_replay(
            self.gp, Either(),
            [{"id": "g", "query": "x", "expect": {"nodes": ["wanted", "wrong"]}}],
            "sha-group", "candidate", source_fingerprint=FP)
        self.assertTrue(run["results"][0]["ok"], "可接受证据组内精确节点命中")


class TestReplayEngine(unittest.TestCase):
    def setUp(self):
        self.tmp, self.gp, self.s = build_workspace()
        probe = self.s.query("共享词", top_k=50, expand=False)
        self.ids = [n["id"] for n in probe["seeds"]]
        self.samples_path = write_samples(
            os.path.join(self.tmp, "samples.json"),
            [{"id": "hit-top1", "query": "共享词", "params": {"top_k": 6},
              "expect": {"node": self.ids[0]}},
             {"id": "deep-target", "query": "共享词", "params": {"top_k": 6},
              "expect": {"node": self.ids[9]}},
             {"id": "neg-refuse", "query": "紫微斗数奇门遁甲毫无关系",
              "params": {"top_k": 6}, "expect": "refused"}])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, label, fp=FP):
        samples, sha = replay.load_samples(self.samples_path)
        return replay.run_replay(self.gp, self.s, samples, sha, label,
                                 source_fingerprint=fp)

    def test_run_records_results_and_manifest(self):
        run = self._run("baseline")
        by_id = {x["id"]: x for x in run["results"]}
        self.assertTrue(by_id["hit-top1"]["ok"])
        self.assertEqual(by_id["hit-top1"]["rank"], 1)
        self.assertFalse(by_id["deep-target"]["ok"], "top_k 外必须 MISS")
        self.assertIsNone(by_id["deep-target"]["rank"])
        self.assertTrue(by_id["neg-refuse"]["ok"])
        for x in run["results"]:
            self.assertTrue(x["event_id"], "逐样本必须绑定记录事件")
        self.assertEqual(run["manifest"]["scorer"], "exact-node-v1")
        stored = replay.get_run(self.gp, run["run_id"])
        self.assertEqual(stored["manifest"]["samples_sha256"],
                         run["samples_sha256"])

    def test_replay_events_isolated_from_user_stats(self):
        from domimap.feedback import FeedbackStore
        before = FeedbackStore(os.path.join(self.tmp, "queries.db")).stats()
        self._run("candidate")
        after = FeedbackStore(os.path.join(self.tmp, "queries.db")).stats()
        self.assertEqual(after["trigger"]["user"], before["trigger"]["user"])
        self.assertGreater(after["trigger"]["non_user"], before["trigger"]["non_user"])

    def test_deterministic_reruns_equal(self):
        a = self._run("baseline")
        b = self._run("candidate")
        cmp_ = replay.compare_runs(a, b)
        self.assertEqual(cmp_["verdict"], "no_change")

    def test_frozen_dimension_mismatch_rejected(self):
        a = self._run("baseline")
        b = self._run("candidate")
        b["manifest"]["graph"]["nodes"] = 999
        with self.assertRaises(ValueError) as cm:
            replay.compare_runs(a, b)
        self.assertIn("graph", str(cm.exception))

    def test_manifestless_old_run_not_comparable(self):
        a = self._run("baseline")
        legacy = {"samples_sha256": a["samples_sha256"], "manifest": None,
                  "summary": {"ok": 0}, "results": a["results"]}
        with self.assertRaises(ValueError) as cm:
            replay.compare_runs(a, legacy)
        self.assertIn("manifest", str(cm.exception))

    def test_sample_set_must_match_exactly(self):
        a = self._run("baseline")
        extra = dict(a)
        extra["results"] = a["results"] + [{"id": "zzz", "ok": False,
                                            "rank": None, "refused": False}]
        with self.assertRaises(ValueError):
            replay.compare_runs(a, extra)

    def test_modified_samples_not_comparable(self):
        run = self._run("baseline")
        write_samples(self.samples_path,
                      [{"id": "hit-top1", "query": "共享词", "params": {"top_k": 6},
                        "expect": {"node": self.ids[0]}}])
        samples, sha = replay.load_samples(self.samples_path)
        run2 = replay.run_replay(self.gp, self.s, samples, sha, "candidate",
                                 source_fingerprint=FP)
        with self.assertRaises(ValueError):
            replay.compare_runs(run, run2)


class TestEvolutionTrace(unittest.TestCase):
    def setUp(self):
        self.tmp, self.gp, self.s = build_workspace(prefix="dm-ev-")
        probe = self.s.query("共享词", top_k=50, expand=False)
        self.target_id = [n["id"] for n in probe["seeds"]][9]
        self.keep_id = [n["id"] for n in probe["seeds"]][0]
        self.samples_path = write_samples(
            os.path.join(self.tmp, "samples.json"),
            [{"id": "target", "query": "共享词", "params": {"top_k": 6},
              "expect": {"node": self.target_id}},
             {"id": "keep", "query": "共享词", "params": {"top_k": 6},
              "expect": {"node": self.keep_id}},
             {"id": "neg", "query": "紫微斗数奇门遁甲毫无关系",
              "params": {"top_k": 6}, "expect": "refused"}])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cluster_fixture(self, query="共享词"):
        from domimap.observation import Recorder, collect_version
        from domimap.feedback import FeedbackStore
        from domimap.diagnosis import build_clusters, diagnose
        ev = Recorder(self.gp).record_query(
            entry="ui", text=query, params={"top_k": 6, "expand": False},
            version=collect_version(self.s, self.gp), status="ok",
            keep_text=True, result={"candidates": []})["event_id"]
        fs = FeedbackStore(os.path.join(self.tmp, "queries.db"))
        try:
            fs.submit(ev, "miss", expected_evidence="docs/g10.md")
        finally:
            fs.close()
        build_clusters(self.gp)
        dg = diagnose(self.gp, self.s, event_id=ev)
        return ev, dg

    def _promoted(self):
        class Promoted(Searcher):
            def query(self, text, **kw):
                kw = dict(kw)
                kw["top_k"] = 50
                r = Searcher.query(self, text, **kw)
                r["seeds"].sort(key=lambda n: n["id"] != target)
                r["seeds"] = r["seeds"][:6]
                return r
        target = self.target_id
        return Promoted(self.s.g)

    def test_record_and_chain_scoped(self):
        ev, dg = self._cluster_fixture()
        cluster = dg["pack"]["cluster_id"]
        samples, sha = replay.load_samples(self.samples_path)
        base = replay.run_replay(self.gp, self.s, samples, sha, "baseline",
                                 source_fingerprint=FP, cluster_id=cluster)
        cand = replay.run_replay(self.gp, self._promoted(), samples, sha, "candidate",
                                 source_fingerprint="fp-cand", cluster_id=cluster)
        roll = replay.run_replay(self.gp, self.s, samples, sha, "rollback",
                                 source_fingerprint=FP, cluster_id=cluster)
        self.assertEqual(replay.compare_runs(base, cand)["verdict"], "improved")
        rec = replay.record_improvement(
            self.gp, cluster, base["run_id"], cand["run_id"], "activated",
            diagnosis_id=dg["diagnosis_id"], rollback_run=roll["run_id"],
            notes="test activation")
        self.assertEqual(rec["decision"], "activated")
        c = replay.chain(self.gp, cluster)
        self.assertEqual(c["cluster"]["cluster_id"], cluster)
        self.assertTrue(any(e["event_id"] == ev for e in c["events"]))
        self.assertTrue(any(f["event_id"] == ev for f in c["feedback"]))
        self.assertTrue(any(d["diagnosis_id"] == dg["diagnosis_id"]
                            for d in c["diagnoses"]))
        # chain 只含关联 run：本簇 3 个，而非工作区全部
        self.assertEqual({r["run_id"] for r in c["replay_runs"]},
                         {base["run_id"], cand["run_id"], roll["run_id"]})
        imp = c["improvements"][0]
        self.assertEqual(imp["decision"], "activated")

    def test_activation_requires_full_lineage(self):
        ev, dg = self._cluster_fixture()
        cluster = dg["pack"]["cluster_id"]
        samples, sha = replay.load_samples(self.samples_path)
        base = replay.run_replay(self.gp, self.s, samples, sha, "baseline",
                                 source_fingerprint=FP)
        cand = replay.run_replay(self.gp, self._promoted(), samples, sha, "candidate",
                                 source_fingerprint="fp-cand")
        # 缺 diagnosis_id
        with self.assertRaises(ValueError):
            replay.record_improvement(self.gp, cluster, base["run_id"],
                                      cand["run_id"], "activated")
        # 不存在的簇（probes.json: invalid_activation）
        with self.assertRaises(ValueError):
            replay.record_improvement(self.gp, "ic:nonexistent", base["run_id"],
                                      cand["run_id"], "activated",
                                      diagnosis_id=dg["diagnosis_id"])
        # 候选指纹 unknown
        cand_unknown = replay.run_replay(self.gp, self._promoted(), samples, sha,
                                         "candidate2", source_fingerprint=None)
        with self.assertRaises(ValueError) as cm:
            replay.record_improvement(self.gp, cluster, base["run_id"],
                                      cand_unknown["run_id"], "activated",
                                      diagnosis_id=dg["diagnosis_id"])
        self.assertIn("指纹", str(cm.exception))

    def test_activation_requires_improved_verdict(self):
        ev, dg = self._cluster_fixture()
        cluster = dg["pack"]["cluster_id"]
        samples, sha = replay.load_samples(self.samples_path)
        a = replay.run_replay(self.gp, self.s, samples, sha, "baseline",
                              source_fingerprint=FP)
        b = replay.run_replay(self.gp, self.s, samples, sha, "candidate",
                              source_fingerprint="fp2")
        with self.assertRaises(ValueError):
            replay.record_improvement(self.gp, cluster, a["run_id"], b["run_id"],
                                      "activated", diagnosis_id=dg["diagnosis_id"])

    def test_activation_requires_equivalent_rollback(self):
        ev, dg = self._cluster_fixture()
        cluster = dg["pack"]["cluster_id"]
        samples, sha = replay.load_samples(self.samples_path)
        base = replay.run_replay(self.gp, self.s, samples, sha, "baseline",
                                 source_fingerprint=FP)
        cand = replay.run_replay(self.gp, self._promoted(), samples, sha, "candidate",
                                 source_fingerprint="fp-cand")
        # 非等价回滚：回滚 run 仍是"候选代码"行为（指纹与基线不同）
        bad_roll = replay.run_replay(self.gp, self._promoted(), samples, sha,
                                     "rollback", source_fingerprint="fp-cand")
        with self.assertRaises(ValueError) as cm:
            replay.record_improvement(self.gp, cluster, base["run_id"],
                                      cand["run_id"], "activated",
                                      diagnosis_id=dg["diagnosis_id"],
                                      rollback_run=bad_roll["run_id"])
        self.assertIn("等价", str(cm.exception))
        # 样本集不一致的回滚同样拒绝
        other = write_samples(os.path.join(self.tmp, "other.json"),
                              [{"id": "x", "query": "共享词", "params": {"top_k": 6},
                                "expect": "refused"}])
        s2, sha2 = replay.load_samples(other)
        roll2 = replay.run_replay(self.gp, self.s, s2, sha2, "rollback",
                                  source_fingerprint=FP)
        with self.assertRaises(ValueError):
            replay.record_improvement(self.gp, cluster, base["run_id"],
                                      cand["run_id"], "activated",
                                      diagnosis_id=dg["diagnosis_id"],
                                      rollback_run=roll2["run_id"])


if __name__ == "__main__":
    unittest.main()
