"""Release 门槛守护：缺真实比较证据时 release-check 必须失败（AC-R14-02 支撑护栏）。

AGENTS.md：release-check 必须在缺真实功能/证据/竞品结果时失败，不能把它改成默认成功。
本测试在当前仓库状态下端到端调用检查器，锁住"未完成即拒绝"的行为。
"""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def run_checker(*args):
    return subprocess.run(
        [sys.executable, "-B", os.path.join(ROOT, "scripts", "check_specs.py"), *args],
        cwd=ROOT, capture_output=True, text=True)

class TestReleaseGate(unittest.TestCase):
    def test_release_fails_without_bundle(self):
        """无真实比较包（out/benchmark/bundle.json 不存在）时 --release 必须非零退出。"""
        bundle = os.path.join(ROOT, "out", "benchmark", "bundle.json")
        if os.path.exists(bundle):
            self.skipTest("bundle 已存在，本护栏应改用坏哈希变体")
        r = run_checker("--release")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_stage_gate_fails_while_cases_pending(self):
        """任一阶段案例未 verified 时 --stage 必须非零退出（用始终未完成的远端阶段做样本）。"""
        r = run_checker("--stage", "M5")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)

if __name__ == "__main__":
    unittest.main()
