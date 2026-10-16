"""Metric definitions and anti-false-pass behavior; no real competitor scores here."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
import evaluate as benchmark  # noqa: E402


class TestBenchmarkMetrics(unittest.TestCase):
    def setUp(self):
        self.protocol = json.loads((ROOT / "benchmarks/protocol.json").read_text())
        self.protocol.update(seeds=[11], bootstrap_iterations=100, minimum_answerable=1, minimum_unanswerable=1, minimum_clusters=2, minimum_answerable_per_category=0)
        self.positive = {"id": "positive", "cluster": "repo-a", "category": "code_location", "answerable": True, "gold_fact_ids": ["fact:version-check"], "allowed_extra_fact_ids": [], "evidence_groups": [["source:mapper-v1:line4"]], "gold_disposition": "answer"}
        self.negative = {"id": "negative", "cluster": "repo-b", "category": "document_reasoning", "answerable": False, "gold_fact_ids": [], "evidence_groups": [], "gold_disposition": "abstain"}

    def prediction(self, case, system="domimap"):
        return {"system": system, "case_id": case["id"], "seed": 11, "status": "ok", "ranked_evidence_ids": ["source:mapper-v1:line4"] if case["answerable"] else [], "support_evidence_ids": ["source:mapper-v1:line4"] if case["answerable"] else [], "fact_ids": list(case["gold_fact_ids"]), "disposition": case["gold_disposition"], "scope_correct": True, "unsupported_material_claim": False}

    def bundle(self):
        systems = {name: {} for name in ["domimap", *self.protocol["baselines"]]}
        return {"kind": "synthetic", "systems": systems, "cases": [self.positive, self.negative], "records": [self.prediction(case, name) for name in systems for case in (self.positive, self.negative)]}

    def test_rank_six_and_fake_similar_ids_cannot_count_as_hit(self):
        record = self.prediction(self.positive)
        record["ranked_evidence_ids"] = ["fake-like-source:mapper-v1:line4"] * 5 + ["source:mapper-v1:line4"]
        self.assertEqual(benchmark.case_counts(self.positive, record)[0], 0)

    def test_wrong_scope_and_invented_facts_lose_credit(self):
        record = self.prediction(self.positive)
        record["scope_correct"] = False
        counts = benchmark.case_counts(self.positive, record)
        self.assertEqual(counts[0], 0)
        self.assertEqual(counts[4:7], [0, 1, 1])
        record["scope_correct"] = True
        record["fact_ids"].append("invented:protection-implemented")
        self.assertEqual(benchmark.case_counts(self.positive, record)[5], 1)

    def test_duplicate_and_allowed_extra_facts_do_not_inflate_tp(self):
        case = copy.deepcopy(self.positive)
        case["allowed_extra_fact_ids"] = ["optional:context"]
        record = self.prediction(case)
        record["fact_ids"] *= 2
        record["fact_ids"].append("optional:context")
        self.assertEqual(benchmark.case_counts(case, record)[4:7], [1, 0, 0])

    def test_unsupported_correct_sounding_fact_is_fp_and_fn(self):
        record = self.prediction(self.positive)
        record["unsupported_material_claim"] = True
        record["unsupported_fact_ids"] = list(record["fact_ids"])
        self.assertEqual(benchmark.case_counts(self.positive, record)[4:7], [0, 1, 1])

    def test_unmapped_unsupported_claim_is_invalid_adjudication(self):
        bundle = self.bundle()
        bundle["records"][0]["unsupported_material_claim"] = True
        with self.assertRaisesRegex(ValueError, "corresponding adjudicated fact"):
            benchmark.evaluate(bundle, self.protocol, ROOT)

    def test_timeout_is_not_correct_abstention(self):
        record = self.prediction(self.negative)
        self.assertEqual(benchmark.case_counts(self.negative, record)[2], 1)
        record["status"] = "timeout"
        self.assertEqual(benchmark.case_counts(self.negative, record)[2], 0)

    def test_missing_baseline_or_run_is_incomplete(self):
        bundle = self.bundle()
        bundle["systems"].pop("graphify")
        with self.assertRaisesRegex(ValueError, "All four"):
            benchmark.evaluate(bundle, self.protocol, ROOT)
        bundle = self.bundle()
        bundle["records"].pop()
        with self.assertRaisesRegex(ValueError, "Incomplete paired"):
            benchmark.evaluate(bundle, self.protocol, ROOT)

    def test_ceiling_tie_is_not_superiority(self):
        report = benchmark.evaluate(self.bundle(), self.protocol, ROOT)
        self.assertNotEqual(report["status"], "pass")
        self.assertEqual(report["comparisons"]["graphify"]["micro_f1"]["difference"], 0)
        self.assertTrue(any("superiority unproven" in item for item in report["gate_reasons"]))

    def test_synthetic_superiority_never_passes_release(self):
        bundle = self.bundle()
        for record in bundle["records"]:
            if record["system"] != "domimap":
                record["fact_ids"] = ["incorrect:claim"]
                record["ranked_evidence_ids"] = []
                record["support_evidence_ids"] = []
                record["disposition"] = "answer"
        report = benchmark.evaluate(bundle, self.protocol, ROOT)
        self.assertEqual(report["status"], "diagnostic_only")
        self.assertGreater(report["comparisons"]["graphify"]["micro_f1"]["lower_bound"], 0)

    def test_bad_real_artifact_hash_rejected(self):
        bundle = self.bundle()
        bundle.update(kind="confirmation", source_fingerprint="a" * 64)
        bundle["common"] = {name: "f" * 64 if name.endswith("_sha256") else "fixture" for name in ("model", "model_version", "host_version", "query_prompt_sha256", "budget_sha256", "dataset_sha256", "gold_sha256")}
        with tempfile.TemporaryDirectory(prefix="domimap-benchmark-") as td:
            path = Path(td) / "run.txt"
            path.write_text("raw fixture")
            bundle["artifacts"] = {"raw": {"path": "run.txt", "sha256": "0" * 64, "role": "raw_output"}}
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                benchmark.evaluate(bundle, self.protocol, Path(td), "a" * 64)

    def test_empty_f1_denominator_is_unknown(self):
        self.assertIsNone(benchmark.metrics([0] * 9)["micro_f1"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
