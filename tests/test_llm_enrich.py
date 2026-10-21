"""llm_enrich 契约（hermetic：注入假客户端/假传输，无网络无费用）。

正例/负例对照 specs/tasks/product-llm-enrich.md：
- LLM 产物一律 inference 草稿 + conf=LLM 标注；人工笔记保持 conf=HUMAN（AC-R05-02）。
- 幂等重跑不重复调用不重复落库；--force 重生成；--dry-run 不联网不落库不写文件。
- 无 key 干净报错（CLI 退出码 6），不静默降级。
- LlmClient 兼容顶层 content 与 message.content 嵌套；thinking 块跳过；瞬时错误有界重试。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from domimap import lite_scan  # noqa: E402
from domimap.graph import Graph, load_seeds  # noqa: E402
from domimap.knowledge import KnowledgeStore, LLM_NOTE_PREFIX, attach_if_present  # noqa: E402
from domimap.llm_enrich import (LlmClient, LlmConfigError, enrich, parse_llm_json,  # noqa: E402
                                select_targets)
from domimap.search import Searcher  # noqa: E402

SEEDS = load_seeds(os.path.join(ROOT, "domimap", "seeds.json"))
LONG = ("订单改价流程说明。" + "改价需要防并发，使用乐观锁与版本号校验。" * 12 +
        "价格同步通过 MQ 广播到下游服务。")  # ≥200 字符，构成合法 Doc 目标
LONG2 = ("库存预警与消费重试策略。" + "消费失败进入重试队列，超过阈值告警。" * 12)
SHORT = "太短"


def build_graph(docs):
    """临时工作区 → scan → Graph.save 到独立输出目录（knowledge.db/审计放它旁边）。"""
    ws = tempfile.mkdtemp(prefix="dm-enrich-ws-")
    out = tempfile.mkdtemp(prefix="dm-enrich-out-")
    for rel, text in docs.items():
        path = os.path.join(ws, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write(text)
    g = Graph()
    g.build_from_records(lite_scan.scan_repo(ws), SEEDS)
    graph_path = os.path.join(out, "graph.json")
    g.save(graph_path)
    return graph_path


GOOD_REPLY = {"summary": "该文档描述订单改价流程，需防并发，价格变更经 MQ 同步。",
              "keywords": ["订单改价", "防并发", "MQ"],
              "claims": [{"statement": "改价流程使用乐观锁防并发",
                          "evidence_paths": ["docs/price.md"]}]}


class FakeClient:
    def __init__(self, replies=None, model="fake-glm"):
        self.model = model
        self.calls = []
        self.replies = list(replies or [])

    def complete(self, system, user):
        self.calls.append((system, user))
        if self.replies:
            item = self.replies.pop(0)
            if isinstance(item, Exception):
                raise item
            return item, {"input_tokens": 10, "output_tokens": 5}
        return json.dumps(GOOD_REPLY, ensure_ascii=False), {"input_tokens": 10}


class TestLlmClient(unittest.TestCase):
    def _resp(self, content):
        return {"content": content, "usage": {"input_tokens": 3}}

    def test_top_level_and_nested_content_shapes_with_thinking_skipped(self):
        thinking = {"type": "thinking", "thinking": "…"}
        text = {"type": "text", "text": "回答"}
        for resp in (self._resp([thinking, text]),
                     {"message": {"content": [text]}, "usage": {}}):
            out, usage = LlmClient(transport=lambda p: resp).complete("s", "u")
            self.assertEqual(out, "回答")
            self.assertTrue(usage is not None)

    def test_bounded_retry_then_success_and_exhaustion(self):
        attempts = []

        def flaky(payload):
            attempts.append(1)
            if len(attempts) < 3:
                raise urllib.error.URLError(OSError("transient"))
            return self._resp([{"type": "text", "text": "ok"}])

        c = LlmClient(transport=flaky, retries=3)
        out, _ = c.complete("s", "u")
        self.assertEqual((out, len(attempts)), ("ok", 3))

        def always_bad(payload):
            raise urllib.error.URLError(OSError("down"))

        with self.assertRaises(urllib.error.URLError):
            LlmClient(transport=always_bad, retries=2).complete("s", "u")

    def test_request_carries_model_system_and_no_key_in_payload(self):
        seen = {}

        def capture(payload):
            seen.update(payload)
            return self._resp([{"type": "text", "text": "x"}])

        LlmClient(model="m1", api_key="k", transport=capture).complete("SYS", "USER")
        self.assertEqual(seen["model"], "m1")
        self.assertEqual(seen["system"], "SYS")
        self.assertEqual(seen["messages"][0]["content"], "USER")
        self.assertNotIn("key", json.dumps(seen))


class TestParse(unittest.TestCase):
    def test_plain_fenced_and_prose_wrapped(self):
        obj = {"summary": "s", "keywords": [], "claims": []}
        self.assertEqual(parse_llm_json(json.dumps(obj, ensure_ascii=False))["summary"], "s")
        self.assertEqual(parse_llm_json("```json\n%s\n```" % json.dumps(obj))["summary"], "s")
        self.assertEqual(parse_llm_json("前言：\n%s\n后记" % json.dumps(obj))["summary"], "s")

    def test_invalid_raises(self):
        for bad in ("", "不是 JSON", json.dumps({"keywords": []})):
            with self.assertRaises(ValueError):
                parse_llm_json(bad)


class TestEnrich(unittest.TestCase):
    def test_writes_inference_draft_with_llm_marker_and_audit(self):
        graph_path = build_graph({"docs/price.md": LONG, "docs/stock.md": LONG2})
        client = FakeClient()
        stats = enrich(graph_path, limit=1, client=client)
        self.assertEqual((stats["notes"], stats["errors"]), (1, 0))
        kb = KnowledgeStore(os.path.join(os.path.dirname(graph_path), "knowledge.db"))
        try:
            notes = kb.list_active()
            self.assertEqual(len(notes), 1)
            body, claims = notes[0]["body"], notes[0]["claims"]
            self.assertTrue(body.startswith(LLM_NOTE_PREFIX), body[:40])
            self.assertIn("source=docs/price.md", body)
            for c in claims:  # 推断不混为事实（AC-R05-02）
                self.assertEqual(c["type"], "inference")
                self.assertEqual(c["state"], "proposed")
            self.assertTrue(all(c["evidence"] == ["docs/price.md"] for c in claims))
        finally:
            kb.close()
        audit = json.load(open(os.path.join(os.path.dirname(graph_path), "enrichment.json"),
                               encoding="utf-8"))
        entry = audit["entries"][-1]
        self.assertEqual(entry["status"], "ok")
        self.assertIn("note_id", entry)
        # 提示词携带材料路径与文本，且系统提示禁止编造
        system, user = client.calls[0]
        self.assertIn("不得编造", system)
        self.assertIn("材料路径：docs/price.md", user)
        self.assertIn("订单改价", user)

    def test_idempotent_rerun_and_force(self):
        graph_path = build_graph({"docs/price.md": LONG})
        client = FakeClient()
        enrich(graph_path, limit=1, client=client)
        stats2 = enrich(graph_path, limit=1, client=client)
        self.assertEqual((stats2["cached"], stats2["notes"]), (1, 0))
        self.assertEqual(len(client.calls), 1)  # 缓存命中不再调用
        kb = KnowledgeStore(os.path.join(os.path.dirname(graph_path), "knowledge.db"))
        try:
            self.assertEqual(kb.count(), 1)
        finally:
            kb.close()
        stats3 = enrich(graph_path, limit=1, client=client, force=True)
        self.assertEqual((stats3["called"], stats3["notes"]), (1, 1))
        self.assertEqual(len(client.calls), 2)

    def test_parse_error_recorded_and_continues(self):
        graph_path = build_graph({"docs/price.md": LONG, "docs/stock.md": LONG2})
        client = FakeClient(replies=["不是 JSON"])
        stats = enrich(graph_path, limit=2, client=client)
        self.assertEqual((stats["notes"], stats["errors"]), (1, 1))
        audit = json.load(open(os.path.join(os.path.dirname(graph_path), "enrichment.json"),
                               encoding="utf-8"))
        self.assertTrue(any(e["status"] == "error" and "parse" in e["error"]
                            for e in audit["entries"]))

    def test_dry_run_makes_no_network_and_no_writes(self):
        graph_path = build_graph({"docs/price.md": LONG, "docs/stock.md": LONG2})
        with mock.patch.dict(os.environ, {}, clear=True):
            stats = enrich(graph_path, limit=2, dry_run=True)
        base = os.path.dirname(graph_path)
        self.assertEqual((stats["dry_run"], stats["called"]), (True, 2))
        self.assertFalse(os.path.exists(os.path.join(base, "knowledge.db")))
        self.assertFalse(os.path.exists(os.path.join(base, "enrichment.json")))

    def test_missing_key_raises_config_error_without_network(self):
        graph_path = build_graph({"docs/price.md": LONG})
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(LlmConfigError, "GLM_API_KEY"):
                enrich(graph_path, limit=1)

    def test_select_targets_respects_limit_and_min_chars(self):
        graph_path = build_graph({"docs/a.md": LONG, "docs/b.md": LONG2, "docs/c.md": SHORT})
        g = Graph.load(graph_path)
        self.assertEqual([n["file"] for n in select_targets(g, 1)],
                         [max(("docs/a.md", LONG), ("docs/b.md", LONG2),
                              key=lambda kv: len(kv[1]))[0]])
        self.assertEqual(len(select_targets(g, 10)), 2)  # SHORT 不入目标


class TestAttachAndVisibility(unittest.TestCase):
    def test_llm_vs_human_marker_in_attach(self):
        graph_path = build_graph({"docs/price.md": LONG})
        base = os.path.dirname(graph_path)
        kb = KnowledgeStore(os.path.join(base, "knowledge.db"))
        human = kb.submit("人工笔记：订单域使用 t_order 表",
                          [{"type": "observation", "statement": "t_order 属订单域",
                            "evidence": [], "scope": ""}])
        llm = kb.submit(LLM_NOTE_PREFIX + "model=m｜source=x】摘要：库存预警重试策略",
                        [{"type": "inference", "statement": "重试有阈值",
                          "evidence": [], "scope": ""}])
        kb.close()
        s = Searcher(Graph.load(graph_path))
        s.attach_knowledge(kb := KnowledgeStore(os.path.join(base, "knowledge.db")))
        kb.close()
        self.assertEqual(s.extra["kn:" + human["note_id"]]["conf"], "HUMAN")
        self.assertEqual(s.extra["kn:" + human["note_id"]]["prov"], "knowledge")
        llm_node = s.extra["kn:" + llm["note_id"]]
        self.assertEqual((llm_node["conf"], llm_node["prov"]), ("LLM", "knowledge:llm"))

    def test_attach_if_present_false_without_db_and_query_hits_knowledge(self):
        graph_path = build_graph({"docs/price.md": LONG})
        base = os.path.dirname(graph_path)
        s = Searcher(Graph.load(graph_path))
        self.assertFalse(attach_if_present(s, graph_path))  # 无 knowledge.db 静默跳过
        kb = KnowledgeStore(os.path.join(base, "knowledge.db"))
        kb.submit(LLM_NOTE_PREFIX + "model=m｜source=docs/price.md】"
                  "订单改价 使用乐观锁防并发，价格变更经 MQ 广播",
                  [{"type": "inference", "statement": "改价防并发", "evidence": ["docs/price.md"],
                    "scope": "docs/price.md"}])
        kb.close()
        s2 = Searcher(Graph.load(graph_path))
        self.assertTrue(attach_if_present(s2, graph_path))
        r = s2.query("订单改价 防并发", top_k=8, seeds=SEEDS)
        kn = [n for n in r["seeds"] if n["kind"] == "Knowledge"]
        self.assertTrue(kn, "增强笔记应可被检索命中")
        self.assertTrue(any(n["conf"] == "LLM" for n in kn))

    def test_cli_enrich_without_key_exits_6(self):
        graph_path = build_graph({"docs/price.md": LONG})
        env = {k: v for k, v in os.environ.items()
               if k not in ("GLM_API_KEY", "ANTHROPIC_API_KEY", "DOMIMAP_LLM_KEY_HELPER")}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        r = subprocess.run([sys.executable, "-B", "-m", "domimap", "enrich", "-g", graph_path],
                           cwd=ROOT, capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 6, r.stdout + r.stderr)
        self.assertIn("GLM_API_KEY", r.stdout + r.stderr)

    def test_knowledge_full_text_indexed_beyond_48char_name(self):
        """回归（真实 GLM e2e 发现）：LLM 溯源前缀超 48 字符时 name 截断后不含摘要中文，
        笔记全文与 claim 陈述必须入索引，否则中文摘要完全不可检索。"""
        graph_path = build_graph({"docs/price.md": LONG})
        base = os.path.dirname(graph_path)
        kb = KnowledgeStore(os.path.join(base, "knowledge.db"))
        kb.submit(LLM_NOTE_PREFIX + "model=glm-5.3｜source=docs/price.md｜text_sha=0123456789abcdef】\n"
                  "订单改价使用乐观锁防并发，冲突时拒绝写入并要求重试。",
                  [{"type": "inference", "statement": "库存预警消费失败进入死信队列",
                    "evidence": [], "scope": ""}])
        kb.close()
        s = Searcher(Graph.load(graph_path))
        attach_if_present(s, graph_path)
        kn = next(iter(s.extra))
        self.assertNotIn("防并发", s.extra[kn]["name"])  # name 已截断，不含摘要中文
        r = s.query("订单改价 防并发", top_k=8, seeds=SEEDS)
        self.assertTrue(any(n["kind"] == "Knowledge" and n["conf"] == "LLM" for n in r["seeds"]),
                        "摘要全文必须可检索")
        r2 = s.query("死信队列 消费失败", top_k=8, seeds=SEEDS)
        self.assertTrue(any(n["kind"] == "Knowledge" for n in r2["seeds"]), "claim 陈述也应可检索")


if __name__ == "__main__":
    unittest.main()
