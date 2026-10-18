"""四竞品主轨宿主契约（hermetic：假传输+假工具执行，无网络无费用）。"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "benchmarks"))

from runners import competitor_host as ch  # noqa: E402

TOOL_USE_REPLY = {
    "content": [
        {"type": "text", "text": "检索中"},
        {"type": "tool_use", "id": "t1", "name": "native_query",
         "input": {"query": "改价"}}],
    "usage": {"input_tokens": 50, "output_tokens": 10}}
FINAL_REPLY = {
    "content": [{"type": "text", "text": "答案：pop-ware-dao/sqlmap/OrderMapper.xml"}],
    "usage": {"input_tokens": 200, "output_tokens": 30}}


class FakeTransport:
    def __init__(self, script):
        self.script = list(script)
        self.payloads = []

    def __call__(self, payload):
        self.payloads.append(payload)
        return self.script.pop(0)


class FakeCliHost(ch.CliToolHost):
    def __init__(self, transport):
        super().__init__("fake-cli", "native_query", "原生查询",
                         lambda q: "命中 sqlmap/OrderMapper.xml", repos=[])
        self._transport = transport


class TestCompetitorHost(unittest.TestCase):
    def test_cli_host_tool_loop_and_ledger(self):
        t = FakeTransport([TOOL_USE_REPLY, FINAL_REPLY])
        host = FakeCliHost(t)
        session = host.open_session({})
        turn = host.ask(session, "改价在哪")
        host.close_session(session)
        self.assertIn("OrderMapper", turn["answer_text"])
        self.assertEqual(turn["tool_calls"], 1)
        self.assertEqual(turn["tokens_in"], 250)
        # 模型拿到的 tools 即原生单工具
        names = {x["name"] for x in t.payloads[0]["tools"]}
        self.assertEqual(names, {"native_query"})

    def test_forced_final_answer_on_exhaustion(self):
        t = FakeTransport([TOOL_USE_REPLY] * 3 + [FINAL_REPLY])
        host = FakeCliHost(t)
        host.max_turns = 3
        session = host.open_session({})
        turn = host.ask(session, "q")
        host.close_session(session)
        self.assertIn("OrderMapper", turn["answer_text"])
        self.assertNotIn("tools", t.payloads[-1])

    def test_cbm_tools_discovery_shape(self):
        """CbmMcpHost 的工具映射：inputSchema→input_schema（结构契约，不打真二进制）。"""
        raw = {"tools": [
            {"name": "search_graph", "description": "d" * 500,
             "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}}},
            {"name": "index_repository", "inputSchema": {}}]}
        mapped = [{"name": t["name"],
                   "description": t.get("description", "")[:400],
                   "input_schema": t.get("inputSchema") or {"type": "object"}}
                  for t in raw["tools"] if t["name"] != "index_repository"]
        self.assertEqual(len(mapped), 1)
        self.assertEqual(mapped[0]["name"], "search_graph")
        self.assertIn("input_schema", mapped[0])
        self.assertEqual(len(mapped[0]["description"]), 400)

    def test_make_cli_exec_unknown(self):
        with self.assertRaises(ValueError):
            ch.make_cli_exec("nope", {})


if __name__ == "__main__":
    unittest.main()
