"""五方适配器契约测试（comparison-native-adapters）：每适配器 ≥20 样例。

修复目标对应旧 formal_run.py 的 P0：gold 路由、静默截断、吞异常、无运行记录。
环境缺失 → SKIP（比较未完成），绝不计为产品失败（specs/benchmark.md §2）。
"""
import inspect
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "benchmarks"))

from adapters import base as abase  # noqa: E402
from adapters.base import (ADAPTER_ERROR, ERROR_CLASSES, OK, PRODUCT_EMPTY,  # noqa: E402
                           TIMEOUT, RepoEntry, assert_no_gold_routing)
from adapters import devfixture  # noqa: E402
from adapters import envs  # noqa: E402


class AdapterContractMixin:
    """子类提供 adapter_cls 与 skip 条件；每类 = 一个适配器的 20+ 契约样例。"""

    adapter_cls = None
    env_key = None  # None 表示无外部环境依赖（domimap）

    @classmethod
    def setUpClass(cls):
        if cls is AdapterContractMixin:
            raise unittest.SkipTest("mixin")
        if cls.env_key is not None:
            env = envs.all_envs()[cls.env_key]
            if not env["available"]:
                raise unittest.SkipTest("env unavailable: %s" % env.get("reason"))
        cls.tmp = tempfile.mkdtemp(prefix="dm-contract-")
        cls.repos, _layout = devfixture.build_fixture(os.path.join(cls.tmp, "ws"))
        cls.artifacts = os.path.join(cls.tmp, "artifacts")
        cls.adapter = cls.adapter_cls(cls.artifacts)
        cls.report = cls.adapter.prepare(cls.repos, {"prepare_timeout": 600,
                                                     "query_timeout": 90})
        if not cls.report.ok_repos:
            raise unittest.SkipTest("prepare failed for all repos: %s"
                                    % cls.report.failed_repos)

    @classmethod
    def tearDownClass(cls):
        if cls is not AdapterContractMixin and hasattr(cls, "adapter"):
            cls.adapter.close()
        if cls is not AdapterContractMixin and hasattr(cls, "tmp"):
            shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- 20 个契约样例 -------------------------------------------------------
    def q(self, text, budget=None):
        return self.adapter.query("sample-%s" % text[:12], text, budget or {})

    def test_01_normal_query_completes(self):
        rec = self.q("订单 改价 changePrice 入口")
        self.assertIn(rec.error_class, ERROR_CLASSES)
        self.assertGreaterEqual(rec.ended, rec.started)

    def test_02_paths_repo_prefixed_and_capped(self):
        rec = self.q("changePrice")
        for p in rec.top5:
            self.assertTrue(p.startswith("repo-alpha/") or p.startswith("repo-beta/"),
                            "路径未映射为 仓名/相对路径: %r" % p)
        self.assertLessEqual(len(rec.top5), 5)

    def test_03_gibberish_is_product_empty(self):
        rec = self.q("xqzwjvbnmkfqpw zzqqxxwwyy")
        self.assertEqual(rec.error_class, PRODUCT_EMPTY)
        self.assertEqual(rec.top5, [])

    def test_04_unique_token_found_in_alpha(self):
        rec = self.q("ZQXW_UNIQUE_TOKEN_9")
        if rec.error_class == OK:
            self.assertTrue(any(p.startswith("repo-alpha/") for p in rec.top5),
                            "唯一 token 未命中 alpha: %s" % rec.top5)

    def test_05_same_name_multi_repo_no_dup(self):
        rec = self.q("OrderService 类")
        self.assertEqual(len(rec.top5), len(set(rec.top5)), "重复路径未去重")

    def test_06_chinese_query(self):
        rec = self.q("库存预警 消费 重试")
        self.assertIn(rec.error_class, ERROR_CLASSES)

    def test_07_chinese_filename_query(self):
        rec = self.q("库存预警消费者")
        self.assertIn(rec.error_class, ERROR_CLASSES)

    def test_08_space_filename_query(self):
        rec = self.q("最终报表 final report")
        self.assertIn(rec.error_class, ERROR_CLASSES)

    def test_09_duplicate_content_dedup(self):
        rec = self.q("重复内容样本")
        self.assertEqual(len(rec.top5), len(set(rec.top5)))

    def test_10_long_output_top5_cap(self):
        rec = self.q("ZQLONG_TOKEN")
        if rec.error_class == OK:
            self.assertLessEqual(len(rec.top5), 5)

    def test_11_special_chars_query(self):
        rec = self.q('检索 "$(特殊)符号"\'测试')
        self.assertIn(rec.error_class, ERROR_CLASSES)

    def test_12_run_id_unique(self):
        r1, r2 = self.q("changePrice"), self.q("changePrice")
        self.assertNotEqual(r1.run_id, r2.run_id)

    def test_13_record_fields_complete(self):
        rec = self.q("字段完整性")
        d = rec.to_dict()
        for key in ("run_id", "question_id", "system", "started", "ended",
                    "error_class", "top5", "raw_path", "notes"):
            self.assertIn(key, d)
        self.assertEqual(d["system"], self.adapter.name)

    def test_14_raw_artifact_verbatim(self):
        rec = self.q("原始输出保存")
        if rec.error_class in (OK, PRODUCT_EMPTY):
            self.assertTrue(rec.raw_path and os.path.isfile(rec.raw_path),
                            "正常/空结果必须保存原始输出工件")
            payload = json.load(open(rec.raw_path, encoding="utf-8"))
            self.assertEqual(payload["run_id"], rec.run_id)
            self.assertTrue(self.adapter.raw_sha256(rec.raw_path))

    def test_15_timeout_classified_not_empty(self):
        rec = self.adapter.query("t15", "changePrice", {"query_timeout": 0.000001})
        if self.adapter.name == "domimap":
            self.assertIn(rec.error_class, ERROR_CLASSES)  # 进程内无子进程超时机制（限制记录）
        else:
            self.assertEqual(rec.error_class, TIMEOUT, "超时被误分类: %s" % rec.error_class)

    def test_16_query_before_prepare(self):
        fresh = self.adapter_cls(os.path.join(self.tmp, "fresh"))
        rec = fresh.query("t16", "anything")
        self.assertEqual(rec.error_class, ADAPTER_ERROR)
        self.assertTrue(any("prepare" in n for n in rec.notes))

    def test_17_prepare_reports_missing_repo(self):
        fresh = self.adapter_cls(os.path.join(self.tmp, "fresh17"))
        report = fresh.prepare(
            [RepoEntry("repo-alpha", self.repos[0].root),
             RepoEntry("repo-ghost", os.path.join(self.tmp, "no-such-dir"))], {})
        names = [f["repo"] for f in report.failed_repos]
        self.assertIn("repo-ghost", names)
        self.assertIn("repo-alpha", report.ok_repos)
        self.assertTrue(all(f.get("reason") for f in report.failed_repos))
        fresh.close()

    def test_18_empty_repo_ready_or_explicitly_failed(self):
        # 空仓：要么进入 ready（可查询），要么显式记入 failed_repos 且有原因——不得静默消失
        ready = [r.name for r in self.adapter.ready_repos]
        failed = [f["repo"] for f in self.report.failed_repos]
        self.assertTrue("repo-empty" in ready or "repo-empty" in failed,
                        "空仓既未就绪也无失败记录")
        if "repo-empty" in ready:
            rec = self.q("空仓查询 changePrice")
            self.assertIn(rec.error_class, (OK, PRODUCT_EMPTY))

    def test_19_prepare_accounting_open(self):
        self.assertTrue(self.report.accounting, "准备阶段无公开记账")

    def test_20_healthy_run_never_env_or_adapter_error(self):
        for text in ("changePrice", "库存预警", "PriceService"):
            rec = self.q(text)
            self.assertIn(rec.error_class, (OK, PRODUCT_EMPTY),
                          "健康环境出现 %s: %s" % (rec.error_class, rec.notes))

    def test_21_repeat_query_consistent_state(self):
        r1 = self.q("一致性 changePrice")
        r2 = self.q("一致性 changePrice")
        self.assertEqual(r1.error_class, r2.error_class)


class TestDomimapAdapter(AdapterContractMixin, unittest.TestCase):
    adapter_cls = None  # 延迟导入避免影响其他类的收集
    env_key = None

    @classmethod
    def setUpClass(cls):
        from adapters.domimap_adapter import DomimapAdapter
        cls.adapter_cls = DomimapAdapter
        super().setUpClass()


class _ExternalAdapterContract(AdapterContractMixin):
    pass


class TestCbmAdapter(_ExternalAdapterContract, unittest.TestCase):
    env_key = "codebase_memory_mcp"

    @classmethod
    def setUpClass(cls):
        from adapters.cbm_adapter import CbmAdapter
        cls.adapter_cls = CbmAdapter
        super().setUpClass()


class TestGraphifyAdapter(_ExternalAdapterContract, unittest.TestCase):
    env_key = "graphify"

    @classmethod
    def setUpClass(cls):
        from adapters.graphify_adapter import GraphifyAdapter
        cls.adapter_cls = GraphifyAdapter
        super().setUpClass()


class TestCodegraphAdapter(_ExternalAdapterContract, unittest.TestCase):
    env_key = "codegraph"

    @classmethod
    def setUpClass(cls):
        from adapters.codegraph_adapter import CodegraphAdapter
        cls.adapter_cls = CodegraphAdapter
        super().setUpClass()


class TestClaudeObsidianAdapter(_ExternalAdapterContract, unittest.TestCase):
    env_key = "claude_obsidian"

    @classmethod
    def setUpClass(cls):
        from adapters.claude_obsidian_adapter import ClaudeObsidianAdapter
        cls.adapter_cls = ClaudeObsidianAdapter
        super().setUpClass()


class TestFrameworkContracts(unittest.TestCase):
    """框架级反路由与合并策略契约（不依赖竞品环境）。"""

    def test_no_gold_routing_in_query_signatures(self):
        from adapters.domimap_adapter import DomimapAdapter
        from adapters.cbm_adapter import CbmAdapter
        from adapters.graphify_adapter import GraphifyAdapter
        from adapters.codegraph_adapter import CodegraphAdapter
        from adapters.claude_obsidian_adapter import ClaudeObsidianAdapter
        for cls in (abase.Adapter, DomimapAdapter, CbmAdapter, GraphifyAdapter,
                    CodegraphAdapter, ClaudeObsidianAdapter):
            self.assertTrue(assert_no_gold_routing(cls), cls.__name__)

    def test_query_signature_is_text_only(self):
        for cls in (abase.Adapter,):
            params = set(inspect.signature(cls.query).parameters)
            self.assertEqual(params - {"self", "cls"}, {"question_id", "text", "budget"})

    def test_round_robin_merge_deterministic_and_dedupe(self):
        a = ["a/1", "a/2", "a/3"]
        b = ["b/1"]
        merged = abase.round_robin_merge([a, b])
        self.assertEqual(merged, ["a/1", "b/1", "a/2", "a/3"])
        self.assertEqual(abase.round_robin_merge([a, ["a/1"]]), ["a/1", "a/2", "a/3"])
        self.assertEqual(abase.round_robin_merge([a, b], cap=2), ["a/1", "b/1"])

    def test_map_to_repo_normalization(self):
        repo = RepoEntry("repo-x", "/tmp/xyz/repo-x")
        self.assertEqual(abase.map_to_repo("/tmp/xyz/repo-x/src/A.java", repo),
                         "repo-x/src/A.java")
        self.assertEqual(abase.map_to_repo("src/A.java", repo), "repo-x/src/A.java")
        self.assertEqual(abase.map_to_repo("/elsewhere/A.java", repo), "/elsewhere/A.java")

    def test_env_missing_raises_not_zero_score(self):
        from adapters.cbm_adapter import CbmAdapter
        with self.assertRaises(EnvironmentError):
            CbmAdapter(tempfile.mkdtemp(), env={"available": False, "reason": "unit-test"})


if __name__ == "__main__":
    unittest.main()
