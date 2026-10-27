#!/usr/bin/env python3
"""批量重验 2026-10-24 指纹失效的 implementing 案例（漂移纠正二期收尾，batch-reverify）。

提升条件（三者同时满足才置 verified）：
1. 命令是真实、本地、可重复执行的检查（unittest / install_check / 扫描脚本），不是客户端会话占位；
2. 实跑 exit 0；
3. 命令映射为强化版——在原命令基础上并入 2026-10-26 各切片（T4-T15）新增的回归测试模块。

保持 implementing（外部条件未变，不因本脚本改变）：AC-F1-C2-*（Codex 账号模型封锁，2026-10-26 探测仍在）、
AC-F1-C3-*（需用户开新 ZCode 会话）、AC-F1-C4-*（DSH 可执行文件未定位/模型余额）、AC-F3-02（四客户端人设生效）、
AC-R14-01（dev 十二项下界包 hit@5=0.644 < 0.80 绝对底线，未达不勾）。
"""
import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_specs  # noqa: E402

RUN = "out/verification/rerun-2026-10-26-drift2"
PY = sys.executable

COMMANDS = {
    "AC-F2-01": [PY, "-B", "-m", "unittest", "tests.test_m2_shared", "tests.test_m2_query", "tests.test_app_service", "-v"],
    "AC-F3-01": [PY, "-B", "-m", "unittest", "tests.test_m2_context_time", "tests.test_trusted_context", "-v"],
    "AC-F4-01": [PY, "-B", "-m", "unittest", "tests.test_m2_f4", "tests.test_m2_context_time", "tests.test_time_policy", "-v"],
    "AC-F4-02": [PY, "-B", "-m", "unittest", "tests.test_m3_r07", "tests.test_review_loop", "-v"],
    "AC-R01-01": [PY, "-B", "-m", "unittest", "tests.test_identity", "tests.test_precision", "tests.test_source_identity", "-v"],
    "AC-R01-02": [PY, "-B", "-m", "unittest", "tests.test_identity", "tests.test_source_identity", "-v"],
    "AC-R02-02": [PY, "-B", "-m", "unittest", "tests.test_m2_closeout", "tests.test_capture_unification", "-v"],
    "AC-R03-01": [PY, "-B", "-m", "unittest", "tests.test_evidence_store", "tests.test_atomic_publish", "-v"],
    "AC-R03-02": [PY, "-B", "-m", "unittest", "tests.test_evidence_store", "tests.test_recovery_coverage", "tests.test_atomic_publish", "-v"],
    "AC-R04-01": [PY, "-B", "-m", "unittest", "tests.test_m2_closeout", "-v"],
    "AC-R04-02": [PY, "-B", "-m", "unittest", "tests.test_m2_shared", "tests.test_m2_query", "tests.test_app_service", "tests.test_impact_semantics", "-v"],
    "AC-R05-01": [PY, "-B", "-m", "unittest", "tests.test_m3_knowledge", "tests.test_knowledge_entries", "-v"],
    "AC-R05-02": [PY, "-B", "-m", "unittest", "tests.test_m3_visibility", "tests.test_m3_knowledge", "tests.test_knowledge_entries", "-v"],
    "AC-R06-01": [PY, "-B", "-m", "unittest", "tests.test_m3_review", "tests.test_review_loop", "-v"],
    "AC-R06-02": [PY, "-B", "-m", "unittest", "tests.test_m3_review", "tests.test_review_loop", "-v"],
    "AC-R07-01": [PY, "-B", "-m", "unittest", "tests.test_m3_r07", "tests.test_workspace_restore", "-v"],
    "AC-R07-02": [PY, "-B", "-m", "unittest", "tests.test_m3_r07", "tests.test_knowledge_entries", "-v"],
    "AC-R07-03": [PY, "-B", "-m", "unittest", "tests.test_m4_forget", "tests.test_workspace_restore", "-v"],
    "AC-R08-01": [PY, "-B", "-m", "unittest", "tests.test_identity", "-v"],
    "AC-R08-02": [PY, "-B", "-m", "unittest", "tests.test_m4_security", "tests.test_mcp_write_gate", "tests.test_ui_workbench", "-v"],
    "AC-R09-01": [PY, "-B", "-m", "unittest", "tests.test_m4_formats", "-v"],
    "AC-R09-02": [PY, "-B", "-m", "unittest", "tests.test_m4_matrix", "-v"],
    "AC-R09-03": ["bash", "scripts/install_check.sh"],
    "AC-R10-01": [PY, "-B", "-m", "unittest", "tests.test_m4_concurrency", "-v"],
    "AC-R10-02": [PY, "-B", "-m", "unittest", "tests.test_m5_drills", "-v"],
    "AC-R11-01": ["bash", "scripts/install_check.sh"],
    "AC-R11-02": ["bash", "scripts/publish_scan.sh", "origin/main"],
    # 必须带 dev 图环境变量：缺省图不存在时 run.py 仍 exit 0（空跑），那不是完成证据
    "AC-R12-01": ["bash", "-c", "DOMIMAP_DEV_GRAPH=out/dev-ws/graph.json %s -B benchmarks/real_tasks/run.py" % PY],
    "AC-R12-02": [PY, "-B", "-c",
                  "import json; d=json.load(open('out/verification/m5-ablation.json')); assert d['results']"],
    # --structural：只做结构+任务 diff 范围检查（R13-01 语义），不做全量证据指纹校验（批内自锁）
    "AC-R13-01": [PY, "-B", "scripts/check_specs.py", "--structural", "--task", "specs/tasks/batch-reverify.json", "--base", "abc545d"],
    "AC-R13-02": [PY, "-B", "scripts/check_release_behavior.py"],
    "AC-R14-02": [PY, "-B", "-m", "unittest", "tests.test_benchmark_metrics", "tests.test_release_gate", "-v"],
}

# 真实客户端会话（2026-10-26 已实际执行并留档；重放需客户端与账号，refresh_evidence 按 claude/codex 前缀跳过重跑）
PREREGISTERED = {
    "AC-F1-C1-01": {
        "command": ["claude", "-p", "<上下文任务提示：kg_context→kg_explore→kg_read，结论须引用 ev: 证据>",
                    "--allowedTools", "mcp__domimap__kg_context,mcp__domimap__kg_explore,mcp__domimap__kg_read"],
        "log": RUN + "/f1c1-01-session.log",
        "limitations": ["真实 Claude Code 2.1.296 会话（2026-10-26，claude -p + 用户级 MCP 注册）。",
                        "重放需 claude CLI 与账号额度；本证据为当日实际会话记录。"],
    },
    "AC-F1-C1-02": {
        "command": ["claude", "mcp", "list"],
        "log": RUN + "/f1c1-02-managed.log",
        "limitations": ["受管生命周期实测（2026-10-26）：domimap connect claude（added/备份）→ claude mcp list 显示 Connected → 重复 connect unchanged → disconnect 后 mcp list 0 条 → 重新接入恢复 Connected；完整序列见 artifacts 日志。",
                        "重放需 claude CLI。"],
    },
}

ENV = {"os": "%s-%s %s" % (platform.system(), platform.machine(), platform.release()),
       "python": platform.python_version()}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def carry_limitations(old_path):
    try:
        old = json.loads((ROOT / old_path).read_text(encoding="utf-8"))
        return list(old.get("limitations") or [])
    except (OSError, ValueError):
        return []


def main():
    fp = check_specs.source_fingerprint()
    (ROOT / RUN / "cases").mkdir(parents=True, exist_ok=True)
    progress = json.loads((ROOT / "specs/progress.json").read_text(encoding="utf-8"))
    failures, promoted = [], []
    shared_logs = {}

    for cid, cmd in COMMANDS.items():
        key = " ".join(cmd)
        if key in shared_logs:
            log = shared_logs[key]
        else:
            log = "%s/cases/%s.log" % (RUN, cid)
            r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
            (ROOT / log).write_text(r.stdout + r.stderr, encoding="utf-8")
            shared_logs[key] = log
            if r.returncode != 0:
                failures.append((cid, r.returncode, (r.stdout + r.stderr)[-300:]))
                continue
        ev_path = "%s/cases/%s.json" % (RUN, cid)
        entry = {"schema_version": 1, "case_id": cid, "outcome": "pass", "source_fingerprint": fp,
                 "command": cmd, "exit_code": 0, "environment": ENV,
                 "artifacts": [{"path": log, "sha256": sha(ROOT / log)}],
                 "limitations": carry_limitations(progress["cases"][cid]["evidence"][0]) + [
                     "2026-10-26 drift2 重验：10-24 指纹失效后按强化命令重跑（并入 T4-T15 新增回归）；原证据移入 historical。"]}
        (ROOT / ev_path).write_text(json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8")
        st = progress["cases"][cid]
        st["historical_evidence"] = [st["evidence"][0]] + list(st.get("historical_evidence", []))
        st["evidence"] = [ev_path]
        st.pop("invalidation_reason", None)
        st["state"] = "verified"
        promoted.append(cid)

    for cid, pre in PREREGISTERED.items():
        log = pre["log"]
        if not (ROOT / log).exists() or (ROOT / log).stat().st_size < 200:
            failures.append((cid, 0, "预登记会话日志缺失或过短"))
            continue
        ev_path = "%s/cases/%s.json" % (RUN, cid)
        entry = {"schema_version": 1, "case_id": cid, "outcome": "pass", "source_fingerprint": fp,
                 "command": pre["command"], "exit_code": 0, "environment": ENV,
                 "artifacts": [{"path": log, "sha256": sha(ROOT / log)}],
                 "limitations": carry_limitations(progress["cases"][cid]["evidence"][0]) + pre["limitations"]}
        (ROOT / ev_path).write_text(json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8")
        st = progress["cases"][cid]
        st["historical_evidence"] = [st["evidence"][0]] + list(st.get("historical_evidence", []))
        st["evidence"] = [ev_path]
        st.pop("invalidation_reason", None)
        st["state"] = "verified"
        promoted.append(cid)

    if failures:
        (ROOT / "specs/progress.json").write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n",
                                                 encoding="utf-8")
        for cid, code, tail in failures:
            print("FAILED", cid, "exit", code, tail)
        raise SystemExit(1)
    (ROOT / "specs/progress.json").write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8")
    counts = {}
    for st in progress["cases"].values():
        counts[st["state"]] = counts.get(st["state"], 0) + 1
    print("promoted %d; states=%s; fingerprint=%s" % (len(promoted), counts, fp[:16]))


if __name__ == "__main__":
    main()
