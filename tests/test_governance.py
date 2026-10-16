"""治理文件守护：M0 基线文件被误删/掏空时测试失败（AC-R13-01 支撑护栏）。"""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class TestGovernanceFiles(unittest.TestCase):
    def test_license_is_mit(self):
        with open(os.path.join(ROOT, "LICENSE"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("MIT License", text)
        self.assertIn("domimap contributors", text)

    def test_governance_docs_exist(self):
        for name in ("SECURITY.md", "CHANGELOG.md", "CONTRIBUTING.md", "THIRD_PARTY_NOTICES.md"):
            self.assertTrue(os.path.getsize(os.path.join(ROOT, name)) > 200, name)

    def test_known_defects_registry_rows(self):
        with open(os.path.join(ROOT, "docs", "known-defects.md"), encoding="utf-8") as f:
            text = f.read()
        for i in range(1, 8):
            self.assertTrue(("| D%d |" % i) in text or ("~~D%d~~" % i) in text,
                            "缺陷登记缺少 D%d" % i)
        # 已关闭行必须注明关闭任务与回归测试，防止口头关闭
        for line in text.split("\n"):
            if "~~D" in line and "已关闭" in line:
                self.assertIn("(", line)
                self.assertIn("回归", line), line
        # 已验证为不复现的旧诊断必须显式记录，防止以讹传讹
        self.assertIn("不复现", text)

    def test_gitignore_excludes_local_outputs(self):
        with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as f:
            text = f.read()
        for token in ("/out/", "dist/", "__pycache__/"):
            self.assertIn(token, text)

if __name__ == "__main__":
    unittest.main()
