#!/usr/bin/env python3
"""诊断轨批量运行器：五系统 × 题 × 重复，独立运行记录。

修复旧 formal_run.py 的执行记录缺陷（无独立 run 证据、覆写运行文件、无预算
记账、无交错）。gold 绝不进入运行器——问题输入只含 id/category/query；评分
输入由裁决环节另行构造。主轨（真实 Agent 会话）扩展点：SYSTEM_FACTORIES
按系统注入宿主会话适配器，接口与诊断适配器一致。
"""
import hashlib
import json
import os
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_RUNS_DIR = os.path.join(ROOT, "out", "diagnostic-runs")
SEEDS = [11, 23, 37, 53, 71]  # 协议重复编号；确定性系统不改行为，仅作记录分组
GOLD_KEYS = {"gold", "gold_path", "answer", "expected", "evidence", "family", "cluster",
             "fact_ids", "necessary_facts"}


def load_questions(path):
    payload = json.load(open(path, encoding="utf-8"))
    questions = payload["questions"]
    for question in questions:
        leaked = GOLD_KEYS & set(question)
        if leaked:
            raise ValueError("question %r leaks gold fields: %s"
                             % (question.get("id"), sorted(leaked)))
        for key in ("id", "category", "query"):
            if not question.get(key):
                raise ValueError("question missing %r" % key)
    return payload, questions


def system_factories():
    """可用系统工厂；env 缺失返回 (None, reason)。主轨适配器在此注册。"""
    def domimap(artifact_dir):
        from adapters.domimap_adapter import DomimapAdapter
        return DomimapAdapter(artifact_dir)

    def cbm(artifact_dir):
        from adapters.cbm_adapter import CbmAdapter
        return CbmAdapter(artifact_dir)

    def graphify(artifact_dir):
        from adapters.graphify_adapter import GraphifyAdapter
        return GraphifyAdapter(artifact_dir)

    def codegraph(artifact_dir):
        from adapters.codegraph_adapter import CodegraphAdapter
        return CodegraphAdapter(artifact_dir)

    def claude_obsidian(artifact_dir):
        from adapters.claude_obsidian_adapter import ClaudeObsidianAdapter
        return ClaudeObsidianAdapter(artifact_dir)

    return {"domimap": domimap, "codebase_memory_mcp": cbm, "graphify": graphify,
            "codegraph": codegraph, "claude_obsidian": claude_obsidian}


def _env_probe(name):
    from adapters import envs
    probes = {"codebase_memory_mcp": envs.cbm_env, "codegraph": envs.codegraph_env,
              "graphify": envs.graphify_env, "claude_obsidian": envs.claude_obsidian_env}
    if name not in probes:
        return None
    env = probes[name]()
    return None if env["available"] else env.get("reason", "unavailable")


def run_batch(question_path, repos, out_dir=None, budget=None, systems=None,
              repeats=None, prepare_hook=None):
    """执行一批诊断轨运行。

    repos: RepoEntry 列表（公开工作区清单，全系统相同）。
    返回 manifest；记录写入 out_dir/<batch_id>/。
    """
    from adapters.base import RepoEntry  # noqa: F401  (类型引用)
    payload, questions = load_questions(question_path)
    repeats = repeats or SEEDS
    budget = budget or {"prepare_timeout": 900, "query_timeout": 90}
    batch_id = "diag-%s" % uuid.uuid4().hex[:12]
    out = os.path.join(out_dir or DEFAULT_RUNS_DIR, batch_id)
    os.makedirs(out, exist_ok=True)

    qhash = hashlib.sha256(open(question_path, "rb").read()).hexdigest()
    manifest = {"schema": "domimap.diagnostic-run.v1", "batch_id": batch_id,
                "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "question_file": os.path.abspath(question_path),
                "question_sha256": qhash, "repeats": repeats,
                "repos": [{"name": r.name, "root": os.path.abspath(r.root)} for r in repos],
                "systems": {}, "skipped": {}, "counts": {}}
    if prepare_hook:
        prepare_hook(manifest)

    active = {}
    for name, factory in (systems or system_factories()).items():
        reason = _env_probe(name)
        if reason:
            manifest["skipped"][name] = reason  # 环境缺失=比较未完成，不算零分
            continue
        artifact_dir = os.path.join(out, "artifacts", name)
        adapter = factory(artifact_dir)
        report = adapter.prepare(repos, budget)
        manifest["systems"][name] = {
            "prepare": report.to_dict(),
            "version_evidence": getattr(adapter, "version", None) or None}
        if not report.ok_repos:
            manifest["skipped"][name] = "prepare failed for all repos: %s" % report.failed_repos
            adapter.close()
            continue
        active[name] = adapter

    counters = {name: 0 for name in active}
    order = list(active)
    os.makedirs(os.path.join(out, "records"), exist_ok=True)
    for repeat in repeats:
        handles = {name: open(os.path.join(out, "records", "%s.rep%d.jsonl"
                                           % (name, repeat)), "w", encoding="utf-8")
                   for name in active}
        try:
            for question in questions:
                # 交错：按题轮转系统起点，避免同一系统独占相邻执行
                start = int(hashlib.sha256(question["id"].encode()).hexdigest()[:6], 16) % len(order)
                for offset in range(len(order)):
                    name = order[(start + offset) % len(order)]
                    record = active[name].query(question["id"], question["query"], budget)
                    entry = record.to_dict()
                    entry["category"] = question["category"]
                    entry["repeat"] = repeat
                    entry["seed_note"] = ("确定性系统：repeat 不改行为，记录独立"
                                          "（protocol 限制如实登记）")
                    handles[name].write(json.dumps(entry, ensure_ascii=False) + "\n")
                    counters[name] += 1
        finally:
            for handle in handles.values():
                handle.close()
    for name, adapter in active.items():
        adapter.close()
    manifest["counts"] = counters
    manifest["records_expected"] = {"per_system": len(questions) * len(repeats),
                                    "systems": sorted(active)}
    with open(os.path.join(out, "run-manifest.json"), "w", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=1)
    return manifest
