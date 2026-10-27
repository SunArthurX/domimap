"""RV04b 回归：workspace policy 与仓级规则的显式优先级（AC-F3-01）。

评审要求"共同工作区规则与仓库规则应有明确优先级"——此前只有 root 选择与歧义报错，无分层。
"""
import json
import os
import tempfile
import unittest

from domimap import mcp
from domimap.graph import build as graph_build
from domimap.service import AppService, ServiceError
from domimap.store import EvidenceStore

WS_POLICY = "# 工作区基线\n\n默认先查证据再回答。\n"
WS_SOUL = "# 工作区人设\n\n中文、简洁。\n"
REPO_A = "# alpha 仓规则\n\nalpha 任务必须先看影响面。\n"
REPO_A_SOUL = "# alpha 人设\n\n面向交易域，谨慎措辞。\n"
REPO_B = "# beta 仓规则\n\nbeta 任务先查上线 checklist。\n"


def _root(base, name, files):
    p = os.path.join(base, name)
    os.makedirs(p, exist_ok=True)
    for fn, text in files.items():
        open(os.path.join(p, fn), "w", encoding="utf-8").write(text)
    return p


class TestWorkspacePolicy(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dm-rv04b-")
        self.addCleanup(tmp.cleanup)
        self.ws = os.path.join(tmp.name, "ws")
        graph_build("tests/fixtures/mini", self.ws)
        self.gp = os.path.join(self.ws, "graph.json")
        self.store = EvidenceStore(os.path.join(self.ws, "store.db"))
        self.addCleanup(self.store.close)
        self.policy = _root(tmp.name, "policy", {"AGENTS.md": WS_POLICY, "SOUL.md": WS_SOUL})
        self.alpha = _root(tmp.name, "alpha", {"AGENTS.md": REPO_A, "SOUL.md": REPO_A_SOUL})
        self.beta = _root(tmp.name, "beta", {"AGENTS.md": REPO_B})

    def _register(self):
        self.store.register_trusted_root("policy", self.policy, level="workspace")
        self.store.register_trusted_root("alpha", self.alpha, level="repo")
        self.store.register_trusted_root("beta", self.beta, level="repo")

    def test_workspace_level_is_single_and_explicit(self):
        self._register()
        other = _root(os.path.dirname(self.policy), "policy2", {"AGENTS.md": "# 另一个\n"})
        with self.assertRaises(ValueError):
            self.store.register_trusted_root("policy2", other, level="workspace")
        roots = {r["label"]: r for r in self.store.trusted_roots()}
        self.assertEqual(roots["policy"]["level"], "workspace")
        self.assertEqual(roots["alpha"]["level"], "repo")
        levels = [r["level"] for r in self.store.trusted_roots()]
        self.assertEqual(levels.count("workspace"), 1)

    def test_repo_rules_override_workspace_same_kind_with_explicit_precedence(self):
        self._register()
        ctx = AppService(self.gp).trusted_context(root="alpha")
        # alpha 仓定义 AGENTS 与 SOUL → 仓级生效，工作区同名被显式取代（不拼接）
        self.assertIn("alpha 仓规则", ctx["text"])
        self.assertNotIn("工作区基线", ctx["text"], "同类别规则仓级覆盖工作区，不得拼接两份 AGENTS")
        self.assertNotIn("工作区人设", ctx["text"], "alpha 定义了 SOUL → 工作区 SOUL 被取代")
        alpha_agents = next(i for i in ctx["items"] if i["root"] == "alpha" and i["path"] == "AGENTS.md")
        self.assertTrue(alpha_agents["effective"])
        self.assertEqual(alpha_agents["level"], "repo")
        ws_agents = next(i for i in ctx["items"] if i["root"] == "policy" and i["path"] == "AGENTS.md")
        self.assertFalse(ws_agents.get("effective"))
        self.assertEqual(ws_agents.get("superseded_by"), "repo:alpha")
        # 优先序显式可读
        self.assertEqual(ctx["precedence"], ["workspace:policy", "repo:alpha"])

    def test_workspace_fills_kinds_repo_does_not_define(self):
        self._register()
        ctx = AppService(self.gp).trusted_context(root="beta")
        # beta 只定义 AGENTS → beta AGENTS 生效；工作区 SOUL（beta 未定义）仍生效
        self.assertIn("beta 仓规则", ctx["text"])
        self.assertIn("工作区人设", ctx["text"], "仓级未定义的类别由工作区基线补位")
        ws_soul = next(i for i in ctx["items"] if i["root"] == "policy" and i["path"] == "SOUL.md")
        self.assertTrue(ws_soul["effective"])
        self.assertEqual(ws_soul["level"], "workspace")

    def test_repo_only_when_no_workspace_policy(self):
        self.store.register_trusted_root("alpha", self.alpha, level="repo")
        self.store.register_trusted_root("beta", self.beta, level="repo")
        with self.assertRaises(ServiceError) as cm:
            AppService(self.gp).trusted_context()  # 多个仓级根（无 workspace）仍歧义
        self.assertEqual(cm.exception.code, "ambiguous_root")
        self.assertIn("仓级", cm.exception.args[0])
        ctx = AppService(self.gp).trusted_context(root="alpha")
        self.assertEqual(ctx["precedence"], ["repo:alpha"])
        self.assertIn("alpha 仓规则", ctx["text"])

    def test_mcp_and_cli_surface_precedence(self):
        self._register()
        out = mcp.Server(self.gp).call("kg_context", {"root": "alpha"})
        self.assertFalse(out["isError"], out)
        body = json.loads(out["content"][0]["text"].splitlines()[0])  # 头部 JSON（其后附上下文文本）
        self.assertEqual(body["precedence"], ["workspace:policy", "repo:alpha"])
        self.assertIn("superseded_by", out["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
