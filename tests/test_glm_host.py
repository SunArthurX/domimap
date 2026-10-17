"""GlmApiHost 契约（hermetic：注入假传输/假桥，无网络无费用）。"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "benchmarks"))

from runners import glm_host as gh  # noqa: E402


class FakeTransport:
    """脚本化响应：第一轮 tool_use，第二轮终答。"""

    def __init__(self, script):
        self.script = list(script)
        self.payloads = []

    def __call__(self, payload):
        self.payloads.append(payload)
        return self.script.pop(0)


class FakeBridge:
    started = closed = False
    calls = []

    def start(self):
        FakeBridge.started = True

    def tool(self, name, arguments):
        FakeBridge.calls.append((name, arguments))
        return "kg_explore 结果：- [Table] t_order_main @ sqlmap/OrderMapper.xml"

    def close(self):
        FakeBridge.closed = True


TOOL_USE_REPLY = {
    "message": {"content": [
        {"type": "text", "text": "我先检索。"},
        {"type": "tool_use", "id": "t1", "name": "kg_explore",
         "input": {"query": "订单改价"}}]},
    "usage": {"input_tokens": 100, "output_tokens": 20}}
FINAL_REPLY = {
    "message": {"content": [
        {"type": "text", "text": "订单改价入口位于 sqlmap/OrderMapper.xml（t_order_main）。"}]},
    "usage": {"input_tokens": 300, "output_tokens": 40}}


class TestGlmHost(unittest.TestCase):
    def _host(self):
        FakeBridge.calls = []
        FakeBridge.started = FakeBridge.closed = False
        return gh.GlmApiHost(
            graph_path="out/x/graph.json",
            transport=FakeTransport([TOOL_USE_REPLY, FINAL_REPLY]),
            bridge_factory=lambda: FakeBridge())

    def test_tool_loop_executes_and_ledger_accumulates(self):
        host = self._host()
        session = host.open_session({"system": "domimap"})
        turn = host.ask(session, "订单改价入口在哪里")
        host.close_session(session)
        self.assertIn("OrderMapper", turn["answer_text"])
        self.assertEqual(turn["tool_calls"], 1)
        self.assertEqual(turn["tokens_in"], 400)
        self.assertEqual(turn["tokens_out"], 60)
        self.assertEqual(FakeBridge.calls, [("kg_explore", {"query": "订单改价"})])
        self.assertTrue(FakeBridge.started and FakeBridge.closed)

    def test_tool_result_fed_back(self):
        host = self._host()
        session = host.open_session({})
        host.ask(session, "q")
        payload2 = host._transport.payloads[1]
        user_msg = payload2["messages"][-1]
        self.assertEqual(user_msg["role"], "user")
        self.assertEqual(user_msg["content"][0]["type"], "tool_result")
        self.assertEqual(user_msg["content"][0]["tool_use_id"], "t1")
        self.assertIn("t_order_main", user_msg["content"][0]["content"])

    def test_no_secret_in_module_text(self):
        source = open(os.path.join(ROOT, "benchmarks", "runners", "glm_host.py"),
                      encoding="utf-8").read()
        # 模块内不得含明文密钥/密钥常量（只有加载逻辑）
        self.assertNotIn("api-key\": \"", source.replace("api-key': \"", ""))
        creds = {"placeholder": True}
        self.assertEqual(len(gh.ENDPOINT), len("https://open.bigmodel.cn/api/anthropic/v1/messages"))

    def test_system_prompt_and_tools_in_payload(self):
        host = self._host()
        session = host.open_session({})
        host.ask(session, "q")
        payload = host._transport.payloads[0]
        self.assertIn("不要编造", payload["system"])
        names = {t["name"] for t in payload["tools"]}
        self.assertEqual(names, {"kg_explore", "kg_read"})

    def test_max_turns_bounds_loop(self):
        endless = FakeTransport([TOOL_USE_REPLY] * 10)
        FakeBridge.calls = []
        host = gh.GlmApiHost("g", transport=endless, bridge_factory=lambda: FakeBridge(),
                             max_turns=3)
        session = host.open_session({})
        turn = host.ask(session, "q")
        host.close_session(session)
        self.assertEqual(turn["tool_calls"], 3, "max_turns 必须限制工具轮数")


if __name__ == "__main__":
    unittest.main()
