"""Check traceability and current verification evidence.

Default (make verify) also requires every verified case's evidence under out/verification to carry
the current source fingerprint and intact artifact hashes. --structural skips only that evidence
check for environments without local artifacts (CI, fresh clones) and never confirms verified
states; --stage/--release additionally gate stages/release and cannot be combined with it.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
STATES = {"planned", "implementing", "verified", "blocked"}
DEPENDENCIES = {"M0": [], "M1": ["M0"], "M2": ["M1"], "M3": ["M2"], "M4": ["M2"], "M5": ["M3", "M4"]}
# Explicit user requirements. R01–R14/F1–F4 from the 2026-10-16 spec; R15 added 2026-10-26 by user
# decision (spec-rehome-r15) so the retrieval-feedback loop stops borrowing R06's identity.
REQUIREMENTS = {"R%02d" % i for i in range(1, 16)} | {"F1-C%d" % i for i in range(1, 5)} | {"F2", "F3", "F4"}


def local_path(root, name):
    if not isinstance(name, str) or not name or Path(name).is_absolute() or ".." in Path(name).parts:
        raise ValueError("Expected a project-relative path: %r" % name)
    path = root / name
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        raise ValueError("Path escapes project: " + name)
    return path


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def source_fingerprint(root=ROOT):
    paths = []
    for name in ("domimap", "tests", "scripts", "benchmarks", "specs", "docs"):
        base = root / name
        if base.exists():
            paths.extend(p for p in base.rglob("*") if p.is_file())
    paths.extend(root / name for name in ("AGENTS.md", "Makefile", "setup.sh", "pyproject.toml", ".gitignore", "README.md") if (root / name).is_file())
    result = hashlib.sha256()
    for path in sorted(set(paths)):
        rel = path.relative_to(root).as_posix()
        if ("__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}
                or rel.startswith("docs/archive/") or rel == "specs/progress.json"
                or rel.startswith("tests/out")):  # 测试生成物（含时间戳的 graph.json）不进指纹
            continue
        result.update(rel.encode("utf-8") + b"\0" + digest(path).encode("ascii") + b"\n")
    return result.hexdigest()


def load(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def check_links(root=ROOT):
    files = [root / name for name in ("README.md", "AGENTS.md") if (root / name).is_file()]
    for name in ("docs", "specs", "benchmarks", "tests"):
        files.extend((root / name).rglob("*.md"))
    count = 0
    for path in files:
        body = path.read_text(encoding="utf-8")
        if len(re.findall(r"^```", body, re.M)) % 2:
            raise ValueError("Unclosed code fence: " + str(path.relative_to(root)))
        for target in re.findall(r"(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)", body):
            target = target.strip("<>").split("#", 1)[0]
            if not target or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
                continue
            count += 1
            if not (path.parent / target).exists():
                raise ValueError("Broken document link: " + str(path.relative_to(root)) + " -> " + target)
    return count


def indexed(items, label):
    result = {}
    for item in items:
        key = item["id"]
        if not isinstance(key, str) or not key or key in result:
            raise ValueError("Duplicate/invalid " + label)
        result[key] = item
    return result


def validate_protocol(protocol):
    baselines = {"claude_obsidian": "https://github.com/AgriciDaniel/claude-obsidian", "codebase_memory_mcp": "https://github.com/DeusData/codebase-memory-mcp", "codegraph": "https://github.com/colbymchenry/codegraph", "graphify": "https://github.com/Graphify-Labs/graphify"}
    if protocol["baselines"] != baselines or protocol["primary_system"] != "domimap" or set(protocol["primary_metrics"]) != {"hit_at_5", "accuracy", "micro_f1"} or len(protocol["primary_metrics"]) != 3:
        raise ValueError("Benchmark must retain all four competitors and three primary metrics")
    floors = {"minimum_answerable": 300, "minimum_unanswerable": 100, "minimum_clusters": 20, "minimum_answerable_per_category": 50, "bootstrap_iterations": 20000}
    numbers = [protocol[key] for key in floors] + [protocol["familywise_alpha"], protocol["minimum_negative_accuracy"], *protocol["minimum_scores"].values()]
    if any(type(value) not in {int, float} or not math.isfinite(value) for value in numbers):
        raise ValueError("Benchmark numeric settings must be finite")
    if any(protocol[key] < value for key, value in floors.items()) or not 0 < protocol["familywise_alpha"] <= 0.05:
        raise ValueError("Benchmark sample/confidence requirements were weakened")
    if any(type(seed) is not int for seed in protocol["seeds"]) or len(set(protocol["seeds"])) < 5 or len(protocol["seeds"]) != len(set(protocol["seeds"])):
        raise ValueError("Benchmark requires at least five distinct seeds")
    if set(protocol["categories"]) != {"code_location", "cross_repo_trace", "document_reasoning", "knowledge_freshness"}:
        raise ValueError("Benchmark task families cannot be dropped")
    if any(protocol["minimum_scores"].get(key, 0) < value for key, value in {"hit_at_5": 0.8, "accuracy": 0.85, "micro_f1": 0.85}.items()) or protocol["minimum_negative_accuracy"] < 0.99:
        raise ValueError("Benchmark quality floors were weakened")
    roles = {"preregistration", "dataset_manifest", "gold_annotation", "baseline_health", "execution_log", "adjudication", "independent_review"}
    if not roles <= set(protocol["required_provenance_roles"]):
        raise ValueError("Benchmark provenance requirements were removed")


def validate(root=ROOT, require_evidence=True):
    req = indexed(load(root / "specs/requirements.json")["requirements"], "requirement")
    cases = indexed(load(root / "specs/acceptance.json")["cases"], "case")
    progress = load(root / "specs/progress.json")
    validate_protocol(load(root / "benchmarks/protocol.json"))
    if set(req) != REQUIREMENTS:
        raise ValueError("Requirement registry changed or missing explicit requirements")
    if set(progress["milestones"]) != set(DEPENDENCIES) or set(progress["cases"]) != set(cases):
        raise ValueError("Progress must account for every stage/case exactly once")
    for path in ("AGENTS.md", "specs/product.md", "specs/workflow.md", "specs/benchmark.md", "docs/roadmap.md", "benchmarks/protocol.json"):
        if not local_path(root, path).is_file():
            raise ValueError("Missing normative file: " + path)
    for rid, item in req.items():
        expected = {cid for cid, case in cases.items() if case["requirement"] == rid}
        if not expected or len(item["cases"]) != len(set(item["cases"])) or set(item["cases"]) != expected:
            raise ValueError("Orphan or mismatched cases for " + rid)
        if not item["milestones"] or not set(item["milestones"]) <= set(DEPENDENCIES):
            raise ValueError("Unknown milestones for " + rid)
    fingerprint = source_fingerprint(root)
    for cid, case in cases.items():
        if case["requirement"] not in req or case["stage"] not in req[case["requirement"]]["milestones"]:
            raise ValueError("Unknown case requirement/stage: " + cid)
        if not all(isinstance(case.get(k), str) and case[k].strip() for k in ("given", "when", "then")):
            raise ValueError("Missing Given/When/Then: " + cid)
        state = progress["cases"][cid]
        if state["state"] not in STATES or not isinstance(state["evidence"], list):
            raise ValueError("Invalid progress: " + cid)
        if state["state"] == "verified":
            if not state["evidence"]:
                raise ValueError("Verified without evidence: " + cid)
            if not require_evidence:
                for name in state["evidence"]:
                    local_path(root, name)
                continue
            for name in state["evidence"]:
                evidence = load(local_path(root, name))
                if evidence.get("case_id") != cid or evidence.get("outcome") != "pass" or type(evidence.get("exit_code")) is not int or evidence["exit_code"] != 0:
                    raise ValueError("Failed/mismatched evidence: " + cid)
                if evidence.get("source_fingerprint") != fingerprint:
                    raise ValueError("Stale verification evidence: " + cid)
                command = evidence.get("command")
                if not isinstance(command, list) or not command or any(not isinstance(part, str) or not part for part in command) or not isinstance(evidence.get("environment"), dict) or not evidence["environment"] or not isinstance(evidence.get("artifacts"), list) or not evidence["artifacts"]:
                    raise ValueError("Evidence lacks command/environment/artifacts: " + cid)
                for artifact in evidence["artifacts"]:
                    if digest(local_path(root, artifact["path"])) != artifact["sha256"]:
                        raise ValueError("Evidence artifact hash mismatch: " + cid)
    for stage, state in progress["milestones"].items():
        if state not in STATES:
            raise ValueError("Invalid stage state: " + stage)
        if state == "verified":
            require_stage(stage, cases, progress)
    return req, cases, progress


def require_stage(stage, cases, progress):
    for dependency in DEPENDENCIES[stage]:
        if progress["milestones"][dependency] != "verified":
            raise ValueError("Unverified dependency: " + dependency)
    pending = [cid for cid, case in cases.items() if case["stage"] == stage and progress["cases"][cid]["state"] != "verified"]
    if pending:
        raise ValueError("Incomplete " + stage + ": " + ", ".join(pending))


def check_task(root, name, req, cases, base=None):
    task = load(local_path(root, name))
    if task.get("state") not in STATES or not task.get("id") or "REPLACE" in task["id"]:
        raise ValueError("Invalid task identity/state")
    if not task.get("requirements") or not set(task["requirements"]) <= set(req):
        raise ValueError("Task has unknown/missing requirements")
    selected = task.get("acceptance_cases", [])
    if not selected or not set(selected) <= set(cases) or any(cases[cid]["requirement"] not in task["requirements"] for cid in selected):
        raise ValueError("Task has unknown/unrelated acceptance cases")
    if not local_path(root, task["spec"]).is_file():
        raise ValueError("Missing task spec")
    files = task.get("files", [])
    if not files or not task.get("test_files") or not set(task["test_files"]) <= set(files):
        raise ValueError("Task needs exact files and test files")
    for path in files:
        local_path(root, path)
        if any(char in path for char in "*?["):
            raise ValueError("Task files must be exact, not broad patterns")
    if base:
        def git(*args):
            return {name for name in subprocess.check_output(["git", *args], cwd=root).decode("utf-8").split("\0") if name}
        changed = git("diff", "--name-only", "-z", base, "--") | git("ls-files", "--others", "--exclude-standard", "-z")
        allowed = set(files) | {name, task["spec"], "specs/progress.json"}
        if changed - allowed:
            raise ValueError("Changes outside task: " + ", ".join(sorted(changed - allowed)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=DEPENDENCIES)
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--bundle", default="out/benchmark/bundle.json")
    parser.add_argument("--task")
    parser.add_argument("--base")
    parser.add_argument("--fingerprint", action="store_true")
    parser.add_argument("--structural", action="store_true",
                        help="skip local evidence verification (CI/fresh clones); never confirms verified states")
    args = parser.parse_args()
    try:
        if args.structural and (args.stage or args.release):
            raise ValueError("--structural cannot gate --stage/--release: those require local evidence")
        req, cases, progress = validate(require_evidence=not args.structural)
        links = check_links()
        if args.base and not args.task:
            raise ValueError("--base requires --task")
        if args.task:
            check_task(ROOT, args.task, req, cases, args.base)
        if args.stage:
            require_stage(args.stage, cases, progress)
        if args.release:
            for stage, state in progress["milestones"].items():
                if state != "verified":
                    raise ValueError("Release incomplete: " + stage)
                require_stage(stage, cases, progress)
            result = subprocess.run([sys.executable, "-B", str(ROOT / "benchmarks/evaluate.py"), "--bundle", str(local_path(ROOT, args.bundle)), "--release"], check=False)
            if result.returncode:
                raise ValueError("Real competitor comparison gate did not pass")
        scope = "release_evidence" if args.release else ("stage_evidence" if args.stage else ("spec_structure_only" if args.structural else "spec_structure"))
        summary = {"scope": scope, "requirements": len(req), "acceptance_cases": len(cases), "verified_cases": sum(s["state"] == "verified" for s in progress["cases"].values()), "evidence_verified": not args.structural}
        summary["local_links_checked"] = links
        if args.fingerprint:
            summary["source_fingerprint"] = source_fingerprint()
        if args.structural:
            print("structural mode: verified states were NOT confirmed (out/verification evidence skipped)", file=sys.stderr)
        print(json.dumps(summary))
        return 0
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as error:
        print("Spec check failed: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
