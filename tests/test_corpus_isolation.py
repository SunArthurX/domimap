"""数据隔离层 v2 契约（comparison-dataset-isolation）。

锁定两个审计缺陷的修复：P1 同大小改内容必被检出；P0 组合/同内容/同前缀来源
归同簇，独立性声明取保守口径。
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "benchmarks"))

from corpus import isolation  # noqa: E402


def make_family(base, name, files):
    root = os.path.join(base, name)
    os.makedirs(root, exist_ok=True)
    for rel, content in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as stream:
            stream.write(content if isinstance(content, bytes)
                         else content.encode("utf-8"))
    return {"family": name, "split": "dev", "root": root}


BIG_A = b"A" * 300
BIG_B = b"B" * 300
SMALL = b"x" * 10


class TestIsolationContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dm-iso-")

    def test_same_size_different_content_changes_signature(self):
        """P1 回归：同大小改内容，族签名必须变化（旧路径+大小哈希检不出）。"""
        f1 = make_family(self.tmp, "f1", {"a.txt": BIG_A})
        f2 = make_family(self.tmp, "f2", {"a.txt": BIG_B})
        m, _ = isolation.build([f1, f2])
        sigs = {f["family"]: f["content_sha256"] for f in m["families"]}
        self.assertEqual(len(sigs), 2)
        self.assertNotEqual(sigs["f1"], sigs["f2"], "同大小内容修改未被检出")

    def test_content_identity_edge_merges_strict(self):
        f1 = make_family(self.tmp, "f1", {"shared/doc.md": BIG_A, "own.txt": BIG_B})
        f2 = make_family(self.tmp, "f2", {"copy/doc.md": BIG_A})
        _, report = isolation.build([f1, f2])
        self.assertEqual(report["strict_cluster_count"], 1)
        self.assertEqual(report["edge_counts"]["content_identity"], 1)

    def test_no_overlap_separate_clusters(self):
        f1 = make_family(self.tmp, "f1", {"a.txt": BIG_A})
        f2 = make_family(self.tmp, "f2", {"a.txt": BIG_B})
        _, report = isolation.build([f1, f2])
        self.assertEqual(report["strict_cluster_count"], 2)

    def test_small_generic_files_do_not_create_edges(self):
        f1 = make_family(self.tmp, "f1", {"boiler": SMALL})
        f2 = make_family(self.tmp, "f2", {"boiler": SMALL})
        _, report = isolation.build([f1, f2])
        self.assertEqual(report["edge_counts"]["content_identity"], 0)
        self.assertEqual(report["strict_cluster_count"], 2)

    def test_os_metadata_files_do_not_create_edges(self):
        """回归：.DS_Store 全机同字节（≥256B），曾把无关族连成假簇。"""
        f1 = make_family(self.tmp, "f1", {"a.txt": BIG_A, ".DS_Store": b"M" * 6148})
        f2 = make_family(self.tmp, "f2", {"a.txt": BIG_B, "sub/.DS_Store": b"M" * 6148})
        _, report = isolation.build([f1, f2])
        self.assertEqual(report["edge_counts"]["content_identity"], 0)
        self.assertEqual(report["strict_cluster_count"], 2)

    def test_standard_license_files_do_not_create_edges(self):
        """回归：MIT/Apache 许可证文本全网同字节，曾把开源族连成假簇。"""
        mit = ("MIT License\n\nPermission is hereby granted, free of charge, to any person "
               "obtaining a copy\n" + "filler\n" * 60).encode()
        f1 = make_family(self.tmp, "f1", {"a.txt": BIG_A, "LICENSE": mit})
        f2 = make_family(self.tmp, "f2", {"a.txt": BIG_B, "LICENSE.md": mit})
        _, report = isolation.build([f1, f2])
        self.assertEqual(report["edge_counts"]["content_identity"], 0)
        self.assertEqual(report["strict_cluster_count"], 2)

    def test_legacy_combo_edge_merges(self):
        f1 = make_family(self.tmp, "f1", {"a.txt": BIG_A})
        f2 = make_family(self.tmp, "f2", {"a.txt": BIG_B})
        qpath = os.path.join(self.tmp, "questions.json")
        with open(qpath, "w", encoding="utf-8") as stream:
            json.dump({"questions": [{"id": "q1", "family": "f1+f2"}]}, stream)
        _, report = isolation.build([f1, f2], qpath)
        self.assertEqual(report["edge_counts"]["legacy_question_combo"], 1)
        self.assertEqual(report["strict_cluster_count"], 1)
        self.assertIn(("f1", "f2"), report["legacy_question_combo_edges"])

    def test_prefix_heuristic_conservative_only(self):
        f1 = make_family(self.tmp, "alpha-core", {"a.txt": BIG_A})
        f2 = make_family(self.tmp, "alpha-web", {"a.txt": BIG_B})
        _, report = isolation.build([f1, f2])
        self.assertEqual(report["strict_cluster_count"], 2, "前缀边不得进 strict 口径")
        self.assertEqual(report["conservative_cluster_count"], 1)
        self.assertIn("conservative", report["independence_claim_basis"])

    def test_short_token_not_merged(self):
        f1 = make_family(self.tmp, "dev-corp-a", {"a.txt": BIG_A})
        f2 = make_family(self.tmp, "dev-corp-b", {"a.txt": BIG_B})
        _, report = isolation.build([f1, f2])
        self.assertEqual(report["conservative_cluster_count"], 2, "短 token 不并簇")

    def test_determinism(self):
        f1 = make_family(self.tmp, "f1", {"a.txt": BIG_A, "d/b.md": b"z" * 400})
        f2 = make_family(self.tmp, "f2", {"a.txt": BIG_B})
        m1, r1 = isolation.build([f1, f2])
        m2, r2 = isolation.build([f1, f2])
        self.assertEqual([f["content_sha256"] for f in m1["families"]],
                         [f["content_sha256"] for f in m2["families"]])
        self.assertEqual(r1["strict_clusters"], r2["strict_clusters"])
        self.assertEqual(r1["conservative_clusters"], r2["conservative_clusters"])

    def test_manifest_schema_and_no_body_leak(self):
        f1 = make_family(self.tmp, "f1", {"a.txt": BIG_A})
        manifest, report = isolation.build([f1])
        fam = manifest["families"][0]
        self.assertEqual(fam["files"], 1)
        self.assertEqual(len(fam["files_inventory"]), 1)
        item = fam["files_inventory"][0]
        self.assertEqual(set(item), {"path", "size", "sha256"})
        self.assertEqual(item["size"], 300)
        self.assertEqual(len(item["sha256"]), 64)
        for key in ("strict_cluster_count", "conservative_cluster_count",
                    "independence_claim_basis", "edge_counts"):
            self.assertIn(key, report)

    def test_explicit_association_merges(self):
        """人工声明的业务关联（如 mall 三变体）必须并簇——自动内容边漏检时不低估关联。"""
        f1 = make_family(self.tmp, "macrozheng-mall", {"a.txt": BIG_A})
        f2 = make_family(self.tmp, "macrozheng-mall-swarm", {"a.txt": BIG_B})
        f3 = make_family(self.tmp, "macrozheng-mall-tiny", {"a.txt": b"C" * 300})
        _, report = isolation.build([f1, f2, f3])
        self.assertEqual(report["edge_counts"]["explicit_association"], 3)
        self.assertEqual(report["strict_cluster_count"], 1)

    def test_confirm_candidate_cluster_accounting(self):
        """确认候选簇只计 confirm-candidate 族；已暴露 dev 族不得混入分母。"""
        f1 = make_family(self.tmp, "dev-corp-giant", {"a.txt": BIG_A})
        f2 = make_family(self.tmp, "dev-corp-mate", {"s.txt": BIG_A})  # 与 dev-corp-giant 同簇
        f3 = make_family(self.tmp, "pub-one", {"a.txt": BIG_B})
        f4 = make_family(self.tmp, "pub-two", {"a.txt": b"C" * 300})
        for f in (f3, f4):
            f["split"] = "confirm-candidate"
        _, report = isolation.build([f1, f2, f3, f4])
        cand = report["confirm_candidate"]
        self.assertEqual(cand["families"], ["pub-one", "pub-two"])
        self.assertEqual(cand["conservative_cluster_count"], 2)
        self.assertEqual(cand["strict_cluster_count"], 2)
        self.assertFalse(cand["meets_protocol_minimum"])
        self.assertEqual(report["conservative_cluster_count"], 3)  # dev-corp 巨簇 + 2 公共

    def test_preregistration_missing_hash_raises(self):
        with self.assertRaises(ValueError):
            isolation.preregistration_draft({}, {},
                                            extra_hashes={"x": None})

    def test_preregistration_draft_fields(self):
        f1 = make_family(self.tmp, "f1", {"a.txt": BIG_A})
        manifest, report = isolation.build([f1])
        manifest["self_sha256"] = "a" * 64
        report["self_sha256"] = "b" * 64
        draft = isolation.preregistration_draft(manifest, report)
        self.assertTrue(draft["batch_id"].startswith("batch-"))
        self.assertIsNone(draft["sealed_by"])
        self.assertIn("candidate", draft)
        self.assertTrue(draft["artifact_hashes"]["corpus_manifest_v2"])


if __name__ == "__main__":
    unittest.main()
