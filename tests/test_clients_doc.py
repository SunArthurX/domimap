"""四客户端调查表守护（M0.4）：clients.md 必须覆盖四客户端且 blocked 项登记所需最小输入。"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class TestClientsDoc(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "docs", "clients.md"), encoding="utf-8") as f:
            self.text = f.read()

    def test_all_four_clients_registered(self):
        for name in ("Claude Code", "Codex", "ZCode", "DSH"):
            self.assertIn(name, self.text)

    def test_blocked_client_declares_minimal_input(self):
        self.assertRegex(self.text, r"blocked.*所需最小输入", "blocked 行必须写明缺什么、要什么")

    def test_only_verified_versions_claimed(self):
        # 已实测的两行必须带版本证据命令；ZCode 行必须含 3.15.3
        self.assertIn("2.1.296", self.text)
        self.assertIn("0.148.0", self.text)
        self.assertIn("3.15.3", self.text)

    def test_pyproject_has_mcp_extra(self):
        with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as f:
            text = f.read()
        self.assertRegex(text, r'(?m)^mcp\s*=\s*\[\s*"mcp>=')

if __name__ == "__main__":
    unittest.main()
