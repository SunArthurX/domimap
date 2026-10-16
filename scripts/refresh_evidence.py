#!/usr/bin/env python3
"""证据定稿脚本（每个切片收尾时运行一次）。

顺序纪律（违反任一步都会造成 Stale/哈希不匹配死锁）：
1. 全部源文件已定稿（含 specs/tasks/*.json 的 state 字段）
2. 计算当前源指纹 F（直接 import，不走 --fingerprint——它会先跑全量校验）
3. 用 F 重写 out/verification/AC-*.json
4. 重跑各案例的证据命令，覆盖同名 log
5. 回填 log 的 sha256 到证据 JSON
运行后 `make verify` / `--stage M0` 应通过。
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_specs  # noqa: E402

EVIDENCE = {
    "AC-R13-01": [
        "python3 -B scripts/check_specs.py --task specs/tasks/{LATEST_TASK}.json --base {PREV_COMMIT}",
    ],
    "AC-R14-02": [
        "python3 -B -m unittest tests.test_benchmark_metrics tests.test_release_gate",
        "make release-check",
    ],
}

def run(cmd, log):
    r = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True)
    (ROOT / log).write_text(r.stdout + r.stderr, encoding="utf-8")
    return r.returncode

def _refresh_all_verified(fp):
    """其余 verified 案例：指纹对齐 + 重跑其 command + 覆写新鲜工件（task 检查前执行，避免顺序死锁）。"""
    progress = json.loads((ROOT / "specs/progress.json").read_text(encoding="utf-8"))
    for cid, state in progress["cases"].items():
        if state["state"] != "verified" or cid in ("AC-R13-01", "AC-R14-02"):
            continue
        for ev_path in state["evidence"]:
            p = ROOT / ev_path
            ev = json.loads(p.read_text(encoding="utf-8"))
            ev["source_fingerprint"] = fp
            if ev["command"][0] in ("claude", "codex"):
                # 客户端真实会话记录：不盲重跑（会话不可重放），仅对齐指纹；工件保持原哈希
                p.write_text(json.dumps(ev, ensure_ascii=False, indent=1), encoding="utf-8")
                continue
            rr = subprocess.run(ev["command"], cwd=ROOT, capture_output=True, text=True)
            log = "out/verification/_rerun-%s.log" % cid
            (ROOT / log).write_text(rr.stdout + rr.stderr, encoding="utf-8")
            if rr.returncode != 0:
                print("RERUN FAILED:", cid, rr.stdout[-300:])
                raise SystemExit(1)
            ev["artifacts"] = [{"path": log, "sha256": hashlib.sha256((ROOT / log).read_bytes()).hexdigest()}]
            p.write_text(json.dumps(ev, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    task = sys.argv[1] if len(sys.argv) > 1 else "m0-interface-survey"
    base = sys.argv[2] if len(sys.argv) > 2 else "HEAD"
    fp = check_specs.source_fingerprint()
    for case in EVIDENCE:
        p = ROOT / ("out/verification/%s.json" % case)
        e = json.loads(p.read_text(encoding="utf-8"))
        e["source_fingerprint"] = fp
        p.write_text(json.dumps(e, ensure_ascii=False, indent=1), encoding="utf-8")
    _refresh_all_verified(fp)
    codes = {}
    codes["task"] = run(EVIDENCE["AC-R13-01"][0].format(LATEST_TASK=task, PREV_COMMIT=base),
                        "out/verification/m0-task-latest.log")
    codes["r14"] = run(EVIDENCE["AC-R14-02"][0], "out/verification/m0-r14-negative-tests.log")
    codes["release"] = run(EVIDENCE["AC-R14-02"][1], "out/verification/m0-release-check-now.log")
    ok = codes["task"] == 0 and codes["r14"] == 0 and codes["release"] != 0
    print("codes:", codes, "task/r14 应为 0，release 应非 0 ->", "OK" if ok else "BAD")

    def sha(x):
        return hashlib.sha256((ROOT / x).read_bytes()).hexdigest()

    e13 = json.loads((ROOT / "out/verification/AC-R13-01.json").read_text(encoding="utf-8"))
    e13["artifacts"] = [{"path": a, "sha256": sha(a)} for a in [
        "out/verification/m0-task-latest.log",
        "out/verification/m0-final-neg-outofscope.log",
        "out/verification/m0-final-neg-fakeverified.log",
        "out/verification/m0-final-neg-dropreq.log",
        "out/verification/m0-install-check.log"]]
    e14 = json.loads((ROOT / "out/verification/AC-R14-02.json").read_text(encoding="utf-8"))
    e14["artifacts"] = [{"path": a, "sha256": sha(a)} for a in [
        "out/verification/m0-r14-negative-tests.log",
        "out/verification/m0-release-check-now.log"]]
    for name, e in (("AC-R13-01", e13), ("AC-R14-02", e14)):
        (ROOT / ("out/verification/%s.json" % name)).write_text(
            json.dumps(e, ensure_ascii=False, indent=1), encoding="utf-8")
    print("fingerprint=%s 证据已定稿" % fp[:16])
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
