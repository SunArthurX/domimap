"""诊断轨运行器契约（comparison-diagnostic-runner）。

锁定：独立运行记录、交错、gold 泄漏拒绝、env 缺失 skip、追加语义。
用 domimap 适配器实跑（无外部依赖）；外部系统走 env 探测路径的伪工厂。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "benchmarks"))

from adapters import devfixture  # noqa: E402
from runners import diagnostic_runner as dr  # noqa: E402


def make_questions(path, extra_fields=False):
    questions = [
        {"id": "q1", "category": "code_location", "query": "订单 改价 changePrice 入口"},
        {"id": "q2", "category": "document_reasoning", "query": "迁移说明 回滚方案 适用版本"},
        {"id": "q3", "category": "negative", "query": "xqzwjvbnmkfqpw zzqqxxwwyy"},
    ]
    if extra_fields:
        questions[0]["gold"] = ["repo-alpha/src/OrderService.java"]
        questions[1]["family"] = "repo-alpha"
    payload = {"questions": questions}
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False)
    return payload


class TestDiagnosticRunner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="dm-runner-")
        cls.repos, _ = devfixture.build_fixture(os.path.join(cls.tmp, "ws"))
        cls.qpath = os.path.join(cls.tmp, "questions.json")
        make_questions(cls.qpath)
        cls.out = os.path.join(cls.tmp, "runs")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _run(self, systems=None, repeats=None):
        return dr.run_batch(self.qpath, self.repos, out_dir=self.out,
                            budget={"prepare_timeout": 120, "query_timeout": 30},
                            # 测试收敛到 domimap（外部系统由 test_adapters_contract 覆盖，
                            # 且默认全系统在本机会真实跑四竞品、拖慢 verify）
                            systems=systems or {"domimap": self._domimap_factory()},
                            repeats=repeats or [11, 23])

    def test_record_counts_exact(self):
        manifest = self._run()
        self.assertEqual(manifest["counts"]["domimap"], 3 * 2)
        self.assertEqual(manifest["records_expected"]["per_system"], 6)

    def test_records_independent_and_complete(self):
        manifest = self._run()
        records = []
        bdir = os.path.join(self.out, manifest["batch_id"], "records")
        for name in os.listdir(bdir):
            with open(os.path.join(bdir, name), encoding="utf-8") as stream:
                records.extend(json.loads(line) for line in stream)
        self.assertEqual(len(records), 6)
        run_ids = [r["run_id"] for r in records]
        self.assertEqual(len(set(run_ids)), len(run_ids), "run_id 必须唯一")
        for record in records:
            self.assertIn(record["error_class"], {"ok", "product_empty", "product_error",
                                                  "env_error", "adapter_error", "timeout"})
            self.assertIn("category", record)
            self.assertIn("repeat", record)
            self.assertTrue(record["raw_path"], "原始工件必须存在")

    def test_repeats_same_output_distinct_records(self):
        manifest = self._run()
        bdir = os.path.join(self.out, manifest["batch_id"], "records")
        rep11 = [json.loads(l) for l in open(os.path.join(bdir, "domimap.rep11.jsonl"))]
        rep23 = [json.loads(l) for l in open(os.path.join(bdir, "domimap.rep23.jsonl"))]
        by_q = {r["question_id"]: r for r in rep11}
        for r in rep23:
            self.assertEqual(r["top5"], by_q[r["question_id"]]["top5"],
                             "确定性系统重复输出应相同")
            self.assertNotEqual(r["run_id"], by_q[r["question_id"]]["run_id"],
                                "重复记录必须独立 run_id")

    def test_gold_leak_rejected(self):
        bad = os.path.join(self.tmp, "bad-questions.json")
        make_questions(bad, extra_fields=True)
        with self.assertRaises(ValueError):
            dr.run_batch(bad, self.repos, out_dir=self.out,
                         systems={"domimap": self._domimap_factory()},
                         repeats=[11])

    def test_env_missing_system_skipped_not_zero(self):
        def raising_factory(_artifact_dir):
            raise AssertionError("不得实例化缺失环境的系统")

        original = dr._env_probe
        dr._env_probe = lambda name: None if name == "domimap" else "unit-test-env-missing"
        try:
            manifest = self._run(systems={"domimap": self._domimap_factory(),
                                          "codebase_memory_mcp": raising_factory})
        finally:
            dr._env_probe = original
        self.assertIn("codebase_memory_mcp", manifest["skipped"])
        self.assertEqual(manifest["skipped"]["codebase_memory_mcp"], "unit-test-env-missing")
        self.assertNotIn("codebase_memory_mcp", manifest["counts"])

    def test_batches_append_not_overwrite(self):
        m1 = self._run()
        m2 = self._run()
        self.assertNotEqual(m1["batch_id"], m2["batch_id"])
        self.assertTrue(os.path.isdir(os.path.join(self.out, m1["batch_id"])))
        self.assertTrue(os.path.isdir(os.path.join(self.out, m2["batch_id"])))

    @staticmethod
    def _domimap_factory():
        def factory(artifact_dir):
            from adapters.domimap_adapter import DomimapAdapter
            return DomimapAdapter(artifact_dir)
        return factory


if __name__ == "__main__":
    unittest.main()
