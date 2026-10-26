"""F3 可信上下文（AC-F3-01）：显式信任登记、嵌套裁决、变更检测、三入口查看、摄入文件不升级为指令。

此前（漂移审计 §2.3/F3 行）：context.load_context 零生产调用；默认 trusted=[root] 自信任；
无嵌套裁决/变更检测/逐客户端记录。AC-F3-02（四客户端桥接生效验证）属 T14，不在本片。
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request

from domimap import mcp
from domimap.context import load_context
from domimap.graph import build as graph_build
from domimap.service import AppService
from domimap.store import EvidenceStore

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MINI = os.path.join(HERE, "fixtures", "mini")


class TestTrustedContext(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dm-f3-")
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.ws = os.path.join(self.tmp, "ws")
        graph_build(MINI, self.ws)
        self.gp = os.path.join(self.ws, "graph.json")
        self.trusted = os.path.join(self.tmp, "trusted")
        os.makedirs(os.path.join(self.trusted, "team"))
        open(os.path.join(self.trusted, "AGENTS.md"), "w", encoding="utf-8").write(
            "# 工作区规则\n\n先查证据，引用出处；无证据明确说未知。\n")
        open(os.path.join(self.trusted, "SOUL.md"), "w", encoding="utf-8").write(
            "# 人设\n\n中文回答，简洁。\n")
        open(os.path.join(self.trusted, "team", "AGENTS.md"), "w", encoding="utf-8").write(
            "# team 规则\n\nteam 子目录任务：改动前先看影响面。\n")

    def _trust(self, label, path):
        from domimap import batch  # noqa: F401
        store = EvidenceStore(os.path.join(self.ws, "store.db"))
        try:
            return store.register_trusted_root(label, path)
        finally:
            store.close()

    def test_load_context_requires_explicit_trust(self):
        with self.assertRaises(PermissionError):
            load_context(self.trusted)  # 不带 trusted：不得自信任（此前默认 trusted=[root]）
        out = load_context(self.trusted, trusted=[self.trusted])
        self.assertTrue(out["items"])

    def test_nested_scope_resolves_to_most_specific(self):
        out = load_context(self.trusted, trusted=[self.trusted])
        agents = [i for i in out["items"] if i["path"].endswith("AGENTS.md")]
        self.assertEqual(len(agents), 2, "两层 AGENTS.md 都要列出（含各自 sha）")
        self.assertEqual([i["path"] for i in agents if i.get("effective")], ["AGENTS.md"],
                         "无任务范围时根层生效，子目录规则只列出不生效（不拼接）")
        scoped = load_context(self.trusted, trusted=[self.trusted], scope="team")
        self.assertEqual([i["path"] for i in scoped["items"] if i["path"].endswith("AGENTS.md") and i.get("effective")],
                         ["team/AGENTS.md"], "任务范围在 team/ 时取最具体一层")
        self.assertNotIn("工作区规则", scoped["text"]); self.assertIn("team 规则", scoped["text"])
        soul = [i for i in out["items"] if i["path"] == "SOUL.md"]
        self.assertTrue(soul[0].get("effective"), "无嵌套时自身生效")
        with self.assertRaises(PermissionError):
            load_context(self.trusted, trusted=[self.trusted], scope="../outside")

    def test_registered_root_loads_and_detects_changes(self):
        self._trust("ws", self.trusted)
        svc = AppService(self.gp)
        first = svc.trusted_context()
        paths = {i["root"] + "/" + i["path"] for i in first["items"]}
        self.assertTrue(any(p.endswith("AGENTS.md") for p in paths), first)
        self.assertEqual(sorted(first["changed"]), sorted("ws/" + i["path"] for i in first["items"]),
                         "首次加载：全部规则文件都是未读（新增）")
        self.assertEqual(AppService(self.gp).trusted_context()["changed"], [], "再次加载无变更")
        self.assertIn("工作区规则", first["text"])
        self.assertNotIn("team 规则", first["text"], "子目录规则不拼接进根范围上下文")
        # 修改（非生效层的）team/AGENTS.md → 下次加载仍报告 changed（变更检测覆盖全部登记文件）
        with open(os.path.join(self.trusted, "team", "AGENTS.md"), "a", encoding="utf-8") as f:
            f.write("\n新增：改动需截图。\n")
        svc2 = AppService(self.gp)
        second = svc2.trusted_context()
        self.assertTrue(any("team/AGENTS.md" in c for c in second["changed"]), second["changed"])
        self.assertIn("新增：改动需截图。", svc2.trusted_context(scope="team")["text"])
        svc3 = AppService(self.gp)
        self.assertEqual(svc3.trusted_context()["changed"], [], "已读变更不再重复报告")

    def test_ingested_rules_are_not_promoted_and_unregistered_roots_rejected(self):
        # mini 夹具里没有 AGENTS.md，先放进一个"普通摄入"的规则文件再重建
        with open(os.path.join(MINI, "AGENTS.md"), "a", encoding="utf-8") as f:
            pass
        self.addCleanup(os.remove, os.path.join(MINI, "AGENTS.md"))
        from domimap import batch
        batch.build_many([os.path.abspath(MINI)], self.ws, force=True,
                         service_prefixes={os.path.abspath(MINI): None})
        svc = AppService(self.gp)
        ctx = svc.trusted_context()
        self.assertFalse(any("fixtures/mini" in i["root"] for i in ctx["items"]),
                         "扫描摄入的 AGENTS.md 不得升级为可信指令（R08：不扩权限）")
        store = EvidenceStore(os.path.join(self.ws, "store.db"))
        try:
            roots = store.trusted_roots()
        finally:
            store.close()
        self.assertFalse(any("fixtures" in r["path"] for r in roots))

    def test_over_budget_is_explicit_not_silent(self):
        self._trust("ws", self.trusted)
        svc = AppService(self.gp)
        ctx = svc.trusted_context(budget=40)
        self.assertTrue(ctx["truncated"])
        self.assertTrue(ctx["dropped"], "被丢弃条目必须列出，不静默截断")

    def test_mcp_kg_context_bridges_trusted_rules(self):
        self._trust("ws", self.trusted)
        srv = mcp.Server(self.gp)
        names = mcp._response(srv, {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        listed = {t["name"] for t in names["result"]["tools"]}
        self.assertIn("kg_context", listed)
        self.assertNotIn("kg_feedback", listed, "默认仍只读 + 上下文工具")
        out = srv.call("kg_context", {"include_text": True})
        self.assertFalse(out["isError"], out)
        text = out["content"][0]["text"]
        self.assertIn("AGENTS.md", text)
        self.assertIn("工作区规则", text)
        scoped = srv.call("kg_context", {"include_text": True, "scope": "team"})["content"][0]["text"]
        self.assertIn("team 规则", scoped)
        self.assertTrue(srv.call("kg_context", {"scope": "../x"})["isError"], "越界范围拒绝")
        # 只读工具不写任何东西；再次调用结果稳定
        self.assertIn("AGENTS.md", srv.call("kg_context", {})["content"][0]["text"])

    def test_cli_trust_and_context_commands(self):
        run = lambda *a: subprocess.run([sys.executable, "-B", "-m", "domimap", *a], cwd=ROOT,
                                        capture_output=True, text=True)
        p = run("trust", "list", "-g", self.gp)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("无", p.stdout)
        p = run("trust", "add", "ws", self.trusted, "-g", self.gp)
        self.assertEqual(p.returncode, 0, p.stderr)
        p = run("trust", "list", "-g", self.gp)
        self.assertIn("ws", p.stdout)
        self.assertIn("AGENTS", p.stdout, "登记时可预览规则文件")
        p = run("context", "-g", self.gp)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("工作区规则", p.stdout)
        self.assertIn("AGENTS.md", p.stdout)
        p = run("context", "-g", self.gp, "--scope", "team")
        self.assertIn("team 规则", p.stdout)
        p = run("trust", "remove", "ws", "-g", self.gp)
        self.assertEqual(p.returncode, 0, p.stderr)
        p = run("context", "-g", self.gp)
        self.assertEqual(p.returncode, 0)
        self.assertIn("未登记", p.stdout)


if __name__ == "__main__":
    unittest.main()
