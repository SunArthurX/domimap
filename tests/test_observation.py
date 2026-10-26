"""retrieval-observation：查询可观测性契约（AC-R06-03）。

- 结构化拒答原因码与 search.py 拒答分支一一对应，判定与文案不变。
- 记录 fail-open：任何记录异常 → recording_failed，查询结果/排序/拒答/exit code 不变。
- 幂等/冲突：同键同内容 duplicate；同键异内容 conflict，原事件不动。
- 隐私默认：不存原文（HMAC 工作区密钥摘要），显式 keep_text 才本地保留。
- 三入口（CLI/MCP/UI）同序同语义，各留独立事件（EV01）。
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import domimap.lite_scan as ls  # noqa: E402
from domimap import observation  # noqa: E402
from domimap.graph import Graph, load_seeds  # noqa: E402
from domimap.observation import ObservationStore, Recorder, run_query  # noqa: E402
from domimap.search import Searcher  # noqa: E402
from domimap.ui import make_server  # noqa: E402


def build_workspace(prefix="dm-obs-"):
    """mini 夹具图 + 落盘 graph.json；返回 (tmp, graph_path, searcher)。"""
    tmp = tempfile.mkdtemp(prefix=prefix)
    ws = os.path.join(tmp, "mini")
    shutil.copytree(os.path.join(HERE, "fixtures", "mini"), ws)
    g = Graph()
    g.build_from_records(ls.scan_repo(ws, repo_label="mini"),
                         load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
    gp = os.path.join(tmp, "graph.json")
    g.save(gp)
    return tmp, gp, Searcher(g)


def build_generic_word_workspace(prefix="dm-obsg-"):
    """合成图：doc/rule.md 含通用词「规则/配置」，触发 generic_only 守门。"""
    tmp = tempfile.mkdtemp(prefix=prefix)
    base = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(base, "doc"))
    with open(os.path.join(base, "doc", "rule.md"), "w", encoding="utf-8") as f:
        f.write("# 规则\n对账流程必须先冻结单据，规则由财务侧维护。\n" + "细节补充\n" * 20)
    R = ls.scan_repo(base)
    g = Graph()
    g.build_from_records(R, load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
    gp = os.path.join(tmp, "graph.json")
    g.save(gp)
    return tmp, gp, Searcher(g)


def db_rows(graph_path, sql, args=()):
    db = sqlite3.connect(os.path.join(os.path.dirname(os.path.abspath(graph_path)),
                                      "queries.db"))
    try:
        return db.execute(sql, args).fetchall()
    finally:
        db.close()


VERSION_STUB = {"domimap": "test", "graph_mtime": 1, "graph_size": 1,
                "nodes": 1, "idx_schema": observation.OBS_SCHEMA}


def record(graph_path, text="订单 改价", status="ok", **kw):
    rec = Recorder(graph_path)
    params = kw.pop("params", {"top_k": 6})
    return rec.record_query(entry=kw.pop("entry", "cli"), text=text, params=params,
                            version=VERSION_STUB, status=status, **kw)


class TestStructuredRefusalReason(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.gp, cls.s = build_workspace()
        cls.tmp_gw, cls.gp_gw, cls.sg = build_generic_word_workspace()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        shutil.rmtree(cls.tmp_gw, ignore_errors=True)

    def test_identifier_absent(self):
        r = self.s.query("ZZZZNotExist123", top_k=6, expand=False)
        self.assertTrue(r["refused"])
        self.assertEqual(r["refusal_reason"], "identifier_absent")
        self.assertNotIn("cov", r)  # 该守门先于覆盖率计算，不伪造数值

    def test_mixed_identifier_absent(self):
        r = self.s.query("t_order_maiqq 表 定义", top_k=6, expand=False)
        self.assertTrue(r["refused"])
        self.assertEqual(r["refusal_reason"], "identifier_absent")
        self.assertEqual(r["min_cov"], 0.3)

    def test_empty_query(self):
        r = self.s.query(" ", top_k=6, expand=False)
        self.assertTrue(r["refused"])
        self.assertEqual(r["refusal_reason"], "empty_query")

    def test_generic_only(self):
        r = self.sg.query("规则", top_k=6, expand=False)
        self.assertTrue(r["refused"], r["text"])
        self.assertEqual(r["refusal_reason"], "generic_only")
        self.assertEqual(r["min_cov"], 0.3)

    def test_coverage_below_min(self):
        r = self.s.query("量子纠缠玄学术语毫无关系", top_k=6, expand=False)
        self.assertTrue(r["refused"])
        self.assertEqual(r["refusal_reason"], "coverage_below_min")
        self.assertLess(r["cov"], 0.3)

    def test_domain_filter_empty(self):
        r = self.s.query("订单", top_k=6, expand=False, domain="不存在的域")
        self.assertTrue(r["refused"])
        self.assertEqual(r["refusal_reason"], "domain_filter_empty")
        self.assertGreaterEqual(r["cov"], 0.3)

    def test_no_strong_candidate(self):
        r = self.s.query("单", top_k=6, expand=False)
        self.assertTrue(r["refused"])
        self.assertEqual(r["refusal_reason"], "no_strong_candidate")

    def test_hit_has_no_reason_and_no_cov_fields(self):
        r = self.s.query("订单", top_k=6, expand=False)
        self.assertFalse(r.get("refused"))
        self.assertIsNone(r.get("refusal_reason"))


class TestRecorderContract(unittest.TestCase):
    def setUp(self):
        self.tmp, self.gp, self.s = build_workspace(prefix="dm-rec-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ok_event_fields_and_candidate_order(self):
        r = self.s.query("订单 改价", top_k=6, expand=False)
        obs = record(self.gp, result=observation.observe_result(r))
        self.assertEqual(obs["status"], "recorded")
        row = db_rows(self.gp, "SELECT entry,status,refusal_reason,query_text,query_len,"
                               "query_has_cjk,query_digest,result_json FROM query_events")[0]
        self.assertEqual(row[0], "cli")
        self.assertEqual(row[1], "ok")
        self.assertIsNone(row[2])
        self.assertIsNone(row[3], "默认隐私：不存查询原文")
        self.assertGreater(row[4], 0)
        self.assertEqual(row[5], 1)
        self.assertRegex(row[6], r"^[0-9a-f]{64}$")
        result = json.loads(row[7])
        self.assertEqual([c["id"] for c in result["candidates"]],
                         [n["id"] for n in r["seeds"]], "候选顺序必须与查询返回一致")

    def test_refused_event_records_reason_and_cov(self):
        r = self.s.query("订单", top_k=6, expand=False, domain="不存在的域")
        obs = record(self.gp, text="订单", status="refused",
                     refusal_reason=r["refusal_reason"], cov=r["cov"], min_cov=r["min_cov"],
                     result=observation.observe_result(r))
        self.assertEqual(obs["status"], "recorded")
        row = db_rows(self.gp, "SELECT status,refusal_reason,cov,min_cov FROM query_events")[0]
        self.assertEqual(row, ("refused", "domain_filter_empty", r["cov"], 0.3))

    def test_idempotent_duplicate(self):
        kw = dict(text="订单 改价", idempotency_key="req-1", params={"top_k": 6},
                  result={"candidates": []})
        first = record(self.gp, **kw)
        second = record(self.gp, **kw)
        self.assertEqual(first["status"], "recorded")
        self.assertEqual(second["status"], "duplicate")
        self.assertEqual(first["event_id"], second["event_id"])
        self.assertEqual(db_rows(self.gp, "SELECT COUNT(*) FROM query_events")[0][0], 1)

    def test_same_key_different_content_is_conflict(self):
        record(self.gp, text="订单 改价", idempotency_key="req-2", params={"top_k": 6},
               result={"candidates": []})
        conflict = record(self.gp, text="订单 改价", idempotency_key="req-2",
                          params={"top_k": 3}, result={"candidates": []})
        self.assertEqual(conflict["status"], "conflict")
        rows = db_rows(self.gp, "SELECT params_json FROM query_events")
        self.assertEqual(len(rows), 1)
        self.assertIn('"top_k":6', rows[0][0], "原事件不得被冲突覆盖")
        self.assertEqual(db_rows(self.gp, "SELECT COUNT(*) FROM idempotency_conflicts")[0][0], 1)

    def test_keep_text_explicit_only(self):
        record(self.gp, text="机密查询原文", keep_text=True, params={"top_k": 6})
        self.assertEqual(db_rows(self.gp, "SELECT query_text FROM query_events")[0][0],
                         "机密查询原文")

    def test_digest_stable_and_workspace_scoped(self):
        tmp2, gp2, _ = build_workspace(prefix="dm-rec2-")
        try:
            h1 = Recorder(self.gp)._hmac("同一查询")
            h1b = Recorder(self.gp)._hmac("同一查询")
            h2 = Recorder(gp2)._hmac("同一查询")
            self.assertEqual(h1, h1b, "同工作区同查询摘要稳定（归并可用）")
            self.assertNotEqual(h1, h2, "跨工作区密钥不同，摘要不可横向比对")
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)

    def test_invalid_values_fail_closed(self):
        obs = record(self.gp, entry="weird")
        self.assertEqual(obs["status"], "recording_failed")
        obs2 = record(self.gp, status="refused", refusal_reason="not_a_code")
        self.assertEqual(obs2["status"], "recording_failed")

    def test_disabled_by_env(self):
        old = os.environ.get("DOMIMAP_OBSERVE")
        os.environ["DOMIMAP_OBSERVE"] = "0"
        try:
            r = run_query(self.gp, self.s, "订单 改价", "cli", {"top_k": 6, "expand": False})
        finally:
            if old is None:
                del os.environ["DOMIMAP_OBSERVE"]
            else:
                os.environ["DOMIMAP_OBSERVE"] = old
        self.assertEqual(r[1]["status"], "disabled")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "queries.db")),
                         "关闭记录时不得创建库")

    def test_recording_failure_fail_open(self):
        # queries.db 位置被目录占用 → 连接失败 → recording_failed，不抛出
        os.mkdir(os.path.join(self.tmp, "queries.db"))
        r, obs = run_query(self.gp, self.s, "订单 改价", "cli", {"top_k": 6, "expand": False})
        self.assertEqual(obs["status"], "recording_failed")
        self.assertIsNone(obs["event_id"])
        self.assertFalse(r.get("refused"))
        self.assertTrue(r["seeds"], "查询结果照常返回")

    def test_query_error_recorded_then_reraised(self):
        class Boom(Searcher):
            def query(self, *a, **kw):
                raise RuntimeError("boom")
        boom = Boom(self.s.g)
        with self.assertRaises(RuntimeError):
            run_query(self.gp, boom, "订单", "cli", {"top_k": 6})
        row = db_rows(self.gp, "SELECT status,result_json FROM query_events")[0]
        self.assertEqual(row[0], "error")
        self.assertIn("RuntimeError", row[1])

    def test_concurrent_records_all_land(self):
        errs = []

        def worker(i):
            try:
                for j in range(20):
                    record(self.gp, text="并发 %d-%d" % (i, j),
                           request_id="batch-%d" % i, params={"top_k": 6})
            except Exception as e:  # 记录链路任何异常都是缺陷（fail-open 只对入口生效）
                errs.append(e)
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errs, [])
        self.assertEqual(db_rows(self.gp, "SELECT COUNT(*) FROM query_events")[0][0], 160)
        ids = db_rows(self.gp, "SELECT event_id FROM query_events")
        self.assertEqual(len({r[0] for r in ids}), 160, "event_id 必须唯一")

    def test_capacity_prune(self):
        old = observation.MAX_EVENTS
        observation.MAX_EVENTS = 5
        try:
            for i in range(12):
                record(self.gp, text="容量 %d" % i, params={"top_k": 6})
            self.assertEqual(db_rows(self.gp, "SELECT COUNT(*) FROM query_events")[0][0], 5)
        finally:
            observation.MAX_EVENTS = old

    def test_parent_and_trigger_linkage(self):
        record(self.gp, text="原始", params={"top_k": 6})
        parent = db_rows(self.gp, "SELECT event_id FROM query_events")[0][0]
        record(self.gp, text="原始", params={"top_k": 6}, trigger_kind="replay",
               parent_event_id=parent, request_id="replay-1")
        rows = db_rows(self.gp, "SELECT trigger_kind,parent_event_id FROM query_events "
                                "WHERE request_id='replay-1'")
        self.assertEqual(rows, [("replay", parent)], "回放/重试必须可关联回原始事件")


class TestDriftC2Identity(unittest.TestCase):
    """drift-correction-c2（F06/F09）：请求身份、密钥并发、版本完整、延迟上界。"""

    def setUp(self):
        self.tmp, self.gp, self.s = build_workspace(prefix="dm-c2-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_duration_not_part_of_request_identity(self):
        # probes.json: retry_idempotency——两次耗时不同仍 duplicate
        from domimap.observation import run_query
        r1 = run_query(self.gp, self.s, "订单 改价", "cli",
                       {"top_k": 6, "expand": False}, idempotency_key="req-c2")
        r2 = run_query(self.gp, self.s, "订单 改价", "cli",
                       {"top_k": 6, "expand": False}, idempotency_key="req-c2")
        self.assertEqual([r1[1]["status"], r2[1]["status"]], ["recorded", "duplicate"])
        # 不同逻辑内容（不同 top_k）仍是冲突而非重复
        r3 = run_query(self.gp, self.s, "订单 改价", "cli",
                       {"top_k": 3, "expand": False}, idempotency_key="req-c2")
        self.assertEqual(r3[1]["status"], "conflict")

    def test_effective_defaults_recorded(self):
        from domimap.observation import run_query
        run_query(self.gp, self.s, "订单 改价", "cli", {"top_k": 6, "expand": False})
        params = json.loads(db_rows(self.gp, "SELECT params_json FROM query_events"
                                    )[0][0])
        for key in ("top_k", "expand", "min_cov", "budget"):
            self.assertIn(key, params, "实际生效参数须含解析后的默认值")

    def test_version_includes_knowledge_and_seeds(self):
        from domimap.observation import collect_version
        v = collect_version(self.s, self.gp)
        self.assertEqual(len(v["seeds_sha256"]), 64, "策略/词表指纹必须入版本")
        self.assertEqual(v["knowledge"], "unknown", "缺失的知识代际如实标 unknown")
        # 建知识库后 knowledge 代际可见
        conn = sqlite3.connect(os.path.join(self.tmp, "knowledge.db"))
        conn.close()
        v2 = collect_version(self.s, self.gp)
        self.assertIn("mtime", v2["knowledge"])
        self.assertIn("size", v2["knowledge"])

    def test_workspace_key_concurrent_creation_single_winner(self):
        from domimap.observation import workspace_key
        keys, errs = [], []

        def worker():
            try:
                keys.append(workspace_key(self.tmp))
            except Exception as e:
                errs.append(e)
        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errs, [])
        self.assertEqual(len(set(keys)), 1, "并发创建必须收敛到唯一赢家密钥")
        self.assertEqual(oct(os.stat(os.path.join(self.tmp, "queries.key")).st_mode)[-3:],
                         "600")

    def test_recording_latency_bound_under_lock(self):
        # F09：库被独占时记录必须在有界时间内失败（fail-open），查询照常返回
        from domimap.observation import ObservationStore, RECORD_LATENCY_BOUND_S
        ObservationStore(os.path.join(self.tmp, "queries.db")).close()
        holder = sqlite3.connect(os.path.join(self.tmp, "queries.db"))
        holder.execute("BEGIN EXCLUSIVE")
        t0 = time.time()
        try:
            from domimap.observation import run_query
            r, obs = run_query(self.gp, self.s, "订单 改价", "cli",
                               {"top_k": 6, "expand": False})
        finally:
            holder.rollback()
            holder.close()
        elapsed = time.time() - t0
        self.assertEqual(obs["status"], "recording_failed")
        self.assertLess(elapsed, RECORD_LATENCY_BOUND_S + 5,
                        "记录失败须在有界时间内返回（实测 %.1fs）" % elapsed)
        self.assertFalse(r.get("refused"))


class TestBehaviorUnchangedWithRecording(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.gp, cls.s = build_workspace(prefix="dm-unch-")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _same(self, text, **kw):
        direct = self.s.query(text, **kw)
        r, obs = run_query(self.gp, self.s, text, "cli", dict(kw))
        self.assertEqual(obs["status"], "recorded")
        self.assertEqual([n["id"] for n in direct["seeds"]], [n["id"] for n in r["seeds"]],
                         text)
        self.assertEqual(direct["text"], r["text"], "渲染文本必须逐字一致")
        self.assertEqual(direct.get("refused"), r.get("refused"))
        self.assertEqual(direct.get("refusal_reason"), r.get("refusal_reason"))

    def test_hit_and_refusal_identical(self):
        self._same("订单 改价", top_k=6, expand=False)
        self._same("量子纠缠玄学术语毫无关系", top_k=6, expand=False)
        self._same("订单", top_k=6, expand=False, domain="不存在的域")


class TestThreeEntriesSharedSemantics(unittest.TestCase):
    """EV01：CLI/MCP/UI 同文本同参数 → 候选同序；各请求独立可追踪记录。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.gp, cls.s = build_workspace(prefix="dm-e3-")
        cls.srv = make_server(cls.gp, port=0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _jget(self, path):
        import urllib.error
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:%d%s" % (self.port, path), timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_cli(self):
        p = subprocess.run([sys.executable, "-m", "domimap", "query", "订单 改价",
                            "-g", self.gp, "--json"],
                           capture_output=True, text=True, cwd=ROOT, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        d = json.loads(p.stdout)
        self.assertEqual(d["recording"], "recorded")
        self.assertTrue(d["query_id"].startswith("qe:"))
        self.assertFalse(d["refused"])
        self.assertTrue(d["seeds"])

    def test_refusal_exit_code_and_stdout_untouched(self):
        p = subprocess.run([sys.executable, "-m", "domimap", "query", "量子纠缠玄学术语",
                            "-g", self.gp], capture_output=True, text=True, cwd=ROOT,
                           timeout=60)
        self.assertEqual(p.returncode, 3, "exit 3 契约不变")
        self.assertIn("诚实拒答", p.stdout)
        self.assertNotIn("qe:", p.stdout, "stdout 不得混入观测信息")
        self.assertIn("观测", p.stderr, "文本模式状态行进 stderr")

    def test_mcp_footer_and_event(self):
        from domimap.mcp import Server
        srv = Server(self.gp)
        out = srv.call("kg_explore", {"query": "订单 改价"})["content"][0]["text"]
        self.assertIn("## 观测", out)
        self.assertIn("recording=recorded", out)
        entries = db_rows(self.gp, "SELECT DISTINCT entry FROM query_events")
        self.assertIn(("mcp",), entries)

    def test_ui_payload_and_shared_order(self):
        code, d = self._jget("/api/search?q=" + urllib.parse.quote("订单 改价"))
        self.assertEqual(code, 200)
        self.assertEqual(d["recording"], "recorded")
        self.assertTrue(d["query_id"].startswith("qe:"))
        ui_ids = [s["id"] for s in d["seeds"]]
        # 三入口候选顺序一致：各入口取最近一条 ok 事件的有序 result_json 对比
        rows = db_rows(self.gp,
                       "SELECT entry, result_json FROM query_events e WHERE status='ok' "
                       "AND created=(SELECT MAX(created) FROM query_events x "
                       "            WHERE x.entry=e.entry AND x.status='ok')")
        by_entry = {e: json.loads(rj)["candidates"] for e, rj in rows}
        base = [c["id"] for c in by_entry["cli"]]
        self.assertTrue(base)
        for entry in ("mcp", "ui"):
            self.assertEqual([c["id"] for c in by_entry[entry]], base,
                             "%s 与 cli 候选顺序不一致" % entry)
        self.assertEqual(ui_ids, base, "UI 响应与记录库同序")
        # 无跨入口合并：三条独立事件
        self.assertGreaterEqual(
            db_rows(self.gp, "SELECT COUNT(*) FROM query_events WHERE "
                             "entry IN ('cli','mcp','ui')")[0][0], 3)

    def test_ui_recording_failure_visible_but_search_ok(self):
        tmp2, gp2, _ = build_workspace(prefix="dm-uifail-")
        try:
            os.mkdir(os.path.join(tmp2, "queries.db"))  # 记录库不可写
            srv = make_server(gp2, port=0)
            port = srv.server_address[1]
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                with urllib.request.urlopen(
                        "http://127.0.0.1:%d/api/search?q=%s"
                        % (port, urllib.parse.quote("订单 改价")), timeout=10) as r:
                    d = json.loads(r.read())
                self.assertEqual(r.status, 200)
                self.assertTrue(d["seeds"], "记录失败时搜索照常返回")
                self.assertEqual(d["recording"], "recording_failed")
                self.assertIsNone(d["query_id"])
            finally:
                srv.shutdown()
                srv.server_close()
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
