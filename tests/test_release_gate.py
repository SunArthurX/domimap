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

    def test_stage_gate_rejects_unknown_and_incomplete(self):
        """未知阶段报错；AC-R14-01 未达绝对底线（证据治理审计更正）时 M5 必须拒绝并指名该案例。"""
        r = run_checker("--stage", "M9")
        self.assertNotEqual(r.returncode, 0)
        r2 = run_checker("--stage", "M5")
        self.assertNotEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        if not os.path.isdir(os.path.join(ROOT, "out", "verification")):
            # 新克隆/CI 没有本地证据：阶段门在证据缺失处即已拒绝（上面已断言）；
            # "指名未完成案例"要求先通过证据校验，只能在有本地证据时断言。
            self.skipTest("本地无 out/verification 证据，跳过指名案例断言（拒绝行为已验证）")
        self.assertIn("AC-R14-01", r2.stderr, "不完整阶段应指名未完成案例")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)

if __name__ == "__main__":
    unittest.main()
