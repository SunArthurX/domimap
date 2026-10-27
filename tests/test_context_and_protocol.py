"""RV04/RV05 回归：可信上下文跨根选择与限制；MCP 协议版本协商与生命周期错误一致性。"""
import json
import os
import tempfile
import unittest

from domimap import mcp
from domimap.graph import build as graph_build
from domimap.service import AppService, ServiceError

ALPHA = "# alpha 根规则\n\n只允许读取 alpha 仓。\n"
BETA = "# beta 根规则\n\nbeta 仓任务须先查影响面。\n"


class TestContextRootSelection(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dm-rv04-")
        self.addCleanup(tmp.cleanup)
        self.ws = os.path.join(tmp.name, "ws")
        graph_build("tests/fixtures/mini", self.ws)
        self.gp = os.path.join(self.ws, "graph.json")
        self.alpha = os.path.join(tmp.name, "alpha")
        self.beta = os.path.join(tmp.name, "beta")
        for p, text in ((self.alpha, ALPHA), (self.beta, BETA)):
            os.makedirs(p)
            open(os.path.join(p, "AGENTS.md"), "w", encoding="utf-8").write(text)

    def _trust(self, label, path):
        from domimap.store import EvidenceStore
        store = EvidenceStore(os.path.join(self.ws, "store.db"))
        try:
            return store.register_trusted_root(label, path)
        finally:
            store.close()

    def test_single_root_defaults_back_compatible(self):
        self._trust("alpha", self.alpha)
        ctx = AppService(self.gp).trusted_context()
        self.assertIn("alpha 根规则", ctx["text"])
        self.assertNotIn("beta", ctx["text"])

    def test_multiple_roots_without_selection_is_structured_ambiguity(self):
        self._trust("alpha", self.alpha)
        self._trust("beta", self.beta)
        with self.assertRaises(ServiceError) as cm:
            AppService(self.gp).trusted_context()
        self.assertEqual(cm.exception.code, "ambiguous_root")
        self.assertIn("alpha", str(cm.exception) and cm.exception.args[0])
        self.assertIn("beta", cm.exception.args[0])
        # 指定根 → 只加载该根
        ctx = AppService(self.gp).trusted_context(root="beta")
        self.assertIn("beta 根规则", ctx["text"])
        self.assertNotIn("alpha 根规则", ctx["text"], "A 仓任务不得串用 B 仓有效规则")
        # 未知根
        with self.assertRaises(ServiceError) as cm:
            AppService(self.gp).trusted_context(root="nope")
        self.assertEqual(cm.exception.code, "invalid_params")

    def test_reading_limits_enforced_before_content(self):
        self._trust("many", self._many_files_root(200))
        ctx = AppService(self.gp).trusted_context(root="many", budget=10 ** 9)
        self.assertTrue(ctx.get("limit_hit") or ctx["truncated"],
                        "文件数/预算超限必须显式截断，不得静默全量")
        dropped = ctx.get("dropped") or []
        self.assertTrue(dropped, "被丢弃文件必须列出")

    def _many_files_root(self, n):
        root = os.path.join(os.path.dirname(self.alpha), "many")
        os.makedirs(root, exist_ok=True)
        open(os.path.join(root, "AGENTS.md"), "w", encoding="utf-8").write("# 主规则\n\n基线。\n")
        for i in range(n):  # 嵌套目录各放一份 AGENTS.md（真实的规则文件形态）
            d = os.path.join(root, "pkg%03d" % i)
            os.makedirs(d)
            open(os.path.join(d, "AGENTS.md"), "w", encoding="utf-8").write("# 子规则 %d\n\n内容 %d。\n" % (i, i))
        return root

    def test_mcp_kg_context_root_param_and_ambiguity(self):
        self._trust("alpha", self.alpha)
        self._trust("beta", self.beta)
        srv = mcp.Server(self.gp)
        out = srv.call("kg_context", {})
        self.assertTrue(out["isError"], "多根未指定 → 结构化歧义错误（isError）")
        body = json.loads(out["content"][0]["text"])
        self.assertEqual(body["code"], "ambiguous_root")
        out = srv.call("kg_context", {"root": "alpha"})
        self.assertFalse(out["isError"], out)
        self.assertIn("alpha 根规则", out["content"][0]["text"])
        self.assertNotIn("beta 根规则", out["content"][0]["text"])


class TestMcpProtocolLifecycle(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dm-rv05-")
        self.addCleanup(tmp.cleanup)
        self.gp = os.path.join(tmp.name, "graph.json")
        import shutil
        shutil.copytree("tests/fixtures/mini", os.path.join(tmp.name, "mini"))
        from domimap.graph import build
        build(os.path.join(tmp.name, "mini"), os.path.join(tmp.name, "ws"))
        self.gp = os.path.join(tmp.name, "ws", "graph.json")

    def _init(self, version):
        srv = mcp.Server(self.gp)
        return mcp._response(srv, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                   "params": {"protocolVersion": version,
                                              "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}})

    def test_protocol_version_negotiated_not_fixed(self):
        r = self._init("2024-11-05")
        self.assertEqual(r["result"]["protocolVersion"], "2024-11-05", "支持的版本应回显客户端请求")
        r2 = self._init("2099-01-01")
        self.assertEqual(r2["result"]["protocolVersion"], mcp.LATEST_PROTOCOL_VERSION,
                         "不支持的版本按规范回服务端最新支持版本（协商而非固定）")

    def test_business_error_then_valid_request_recovers(self):
        srv = mcp.Server(self.gp, enable_write=True)
        bad = srv.call("kg_note", {"action": "accept", "note_id": "kn:nope",
                                   "claim_idx": 0, "expected_revision": 1, "statement": "x"})
        self.assertTrue(bad["isError"])
        self.assertEqual(json.loads(bad["content"][0]["text"])["code"], "forbidden")
        good = srv.call("kg_explore", {"query": "订单改价"})
        self.assertFalse(good["isError"], "业务失败后的有效请求必须仍可执行")


if __name__ == "__main__":
    unittest.main()
