"""Score adjudicated paired outputs; synthetic/missing evidence never passes release."""

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_specs import digest, local_path, source_fingerprint, validate_protocol  # noqa: E402


def strings(value, label):
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError("Expected string list: " + label)
    return value


def sha256_text(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def metrics(counts):
    hit, answerable, correct, total, tp, fp, fn, neg_correct, negatives = counts
    return {"hit_at_5": hit / answerable if answerable else None,
            "accuracy": correct / total if total else None,
            "micro_f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "negative_accuracy": neg_correct / negatives if negatives else None}


def case_counts(case, record):
    expected = set(case["gold_fact_ids"])
    allowed = set(case.get("allowed_extra_fact_ids", []))
    ok = record["status"] == "ok"
    predicted = set(record["fact_ids"]) if ok else set()
    unsupported = set(record.get("unsupported_fact_ids", [])) if ok else set()
    ranked = record["ranked_evidence_ids"][:5] if ok else []
    support = set(record["support_evidence_ids"]) if ok else set()
    groups = [set(group) for group in case["evidence_groups"]]
    applicable = record["scope_correct"]
    tp = len((predicted - unsupported) & expected) if applicable else 0
    fp = len((predicted - expected - allowed) | unsupported) if applicable else len(predicted)
    fn = len(expected) - tp
    hit = int(bool(case["answerable"] and applicable and any(set(ranked) & group for group in groups)))
    correct = int(ok and applicable and record["disposition"] == case["gold_disposition"] and not record["unsupported_material_claim"] and fp == 0 and fn == 0 and all(support & group for group in groups))
    negative = not case["answerable"]
    return [hit, int(case["answerable"]), correct, 1, tp, fp, fn, correct if negative else 0, int(negative)]


def validate_bundle(bundle, protocol, directory, expected_fingerprint):
    if bundle.get("kind") not in {"synthetic", "confirmation"}:
        raise ValueError("Bundle kind must be synthetic or confirmation")
    system_ids = [protocol["primary_system"], *protocol["baselines"]]
    systems = bundle["systems"]
    if set(systems) != set(system_ids):
        raise ValueError("All four baselines and domimap must be present; missing is not zero")
    cases = {}
    for case in bundle["cases"]:
        cid = case["id"]
        if not isinstance(cid, str) or not cid or cid in cases or not case.get("cluster"):
            raise ValueError("Duplicate/invalid case or missing cluster")
        if type(case["answerable"]) is not bool or case["category"] not in protocol["categories"]:
            raise ValueError("Invalid answerability/category")
        facts = strings(case["gold_fact_ids"], "gold facts")
        strings(case.get("allowed_extra_fact_ids", []), "allowed facts")
        if not isinstance(case["evidence_groups"], list):
            raise ValueError("Evidence groups must be a list")
        for group in case["evidence_groups"]:
            if not strings(group, "evidence group"):
                raise ValueError("Empty evidence group")
        if case["answerable"]:
            if not facts or not case["evidence_groups"] or case["gold_disposition"] != "answer":
                raise ValueError("Answerable case needs facts, evidence and answer disposition")
        elif facts or case["gold_disposition"] not in {"abstain", "clarify"}:
            raise ValueError("Negative case must not manufacture positive facts")
        cases[cid] = case
    if not cases:
        raise ValueError("Empty dataset")
    records = {}
    for record in bundle["records"]:
        key = (record["system"], record["case_id"], record["seed"])
        if key in records or key[0] not in systems or key[1] not in cases or key[2] not in protocol["seeds"]:
            raise ValueError("Duplicate/unregistered system, case or seed")
        if record["status"] not in {"ok", "timeout", "error", "unsupported"}:
            raise ValueError("Unknown status")
        for name in ("ranked_evidence_ids", "support_evidence_ids", "fact_ids"):
            strings(record[name], name)
        unsupported = set(strings(record.get("unsupported_fact_ids", []), "unsupported facts"))
        if not unsupported <= set(record["fact_ids"]) or bool(unsupported) != record["unsupported_material_claim"]:
            raise ValueError("Unsupported claims require corresponding adjudicated fact IDs")
        if type(record["scope_correct"]) is not bool or type(record["unsupported_material_claim"]) is not bool:
            raise ValueError("Judgment flags must be booleans")
        if record["disposition"] not in {"answer", "abstain", "clarify"}:
            raise ValueError("Unknown disposition")
        records[key] = record
    expected = {(system, cid, seed) for system in systems for cid in cases for seed in protocol["seeds"]}
    if set(records) != expected:
        raise ValueError("Incomplete paired runs: every system/case/seed is mandatory")
    if bundle["kind"] == "confirmation":
        if not expected_fingerprint or bundle.get("source_fingerprint") != expected_fingerprint:
            raise ValueError("Missing/stale domimap source fingerprint")
        common = bundle["common"]
        keys = ("model", "model_version", "host_version", "query_prompt_sha256", "budget_sha256", "dataset_sha256", "gold_sha256")
        if not all(isinstance(common.get(key), str) and common[key] for key in keys):
            raise ValueError("Missing frozen environment/data/budget metadata")
        if any(not sha256_text(common[key]) for key in keys if key.endswith("_sha256")):
            raise ValueError("Frozen metadata must contain actual SHA-256 values")
        artifacts = bundle["artifacts"]
        roles = set()
        for item in artifacts.values():
            if digest(local_path(directory, item["path"])) != item["sha256"]:
                raise ValueError("Comparison artifact hash mismatch")
            roles.add(item["role"])
        if not set(protocol["required_provenance_roles"]) <= roles:
            raise ValueError("Missing preregistration/gold/review/execution provenance")
        for key, role in (("dataset_sha256", "dataset_manifest"), ("gold_sha256", "gold_annotation")):
            if not any(item["role"] == role and item["sha256"] == common[key] for item in artifacts.values()):
                raise ValueError("Frozen dataset/gold hash does not match its artifact")
        for info in systems.values():
            revision = info.get("revision", "")
            if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
                raise ValueError("System revision must be an immutable Git SHA")
            if info.get("health") != "ok" or not sha256_text(info.get("config_sha256")) or any(info.get(key) != common[key] for key in keys):
                raise ValueError("Unhealthy baseline or unequal frozen settings")
        for record in records.values():
            for key, role in (("raw_artifact_id", "raw_output"), ("judgment_artifact_id", "judgment")):
                if record.get(key) not in artifacts or artifacts[record[key]]["role"] != role:
                    raise ValueError("A run lacks raw output or independent judgment artifact")
    return system_ids, cases, records


def evaluate(bundle, protocol, directory, expected_fingerprint=None):
    systems, cases, records = validate_bundle(bundle, protocol, directory, expected_fingerprint)
    by_cluster = {system: defaultdict(lambda: [0] * 9) for system in systems}
    for (system, cid, seed), record in records.items():
        values = case_counts(cases[cid], record)
        bucket = by_cluster[system][cases[cid]["cluster"]]
        for i, value in enumerate(values):
            bucket[i] += value
    clusters = sorted({case["cluster"] for case in cases.values()})
    totals = {system: [sum(values[i] for values in by_cluster[system].values()) for i in range(9)] for system in systems}
    scores = {system: metrics(values) for system, values in totals.items()}
    primary = protocol["primary_system"]
    names = protocol["primary_metrics"]
    samples = {(baseline, name): [] for baseline in protocol["baselines"] for name in names}
    rng = random.Random(protocol["bootstrap_seed"])
    iterations = protocol["bootstrap_iterations"]
    valid = attempts = 0
    while valid < iterations and attempts < iterations * 10:
        attempts += 1
        selected = rng.choices(clusters, k=len(clusters))
        draws = {system: metrics([sum(by_cluster[system][cluster][i] for cluster in selected) for i in range(9)]) for system in systems}
        if any(draws[system][name] is None for system in systems for name in names):
            continue
        valid += 1
        for (baseline, name), values in samples.items():
            values.append(draws[primary][name] - draws[baseline][name])
    alpha = protocol["familywise_alpha"] / len(samples)
    comparisons = {}
    for (baseline, name), values in samples.items():
        point = scores[primary][name]
        opponent = scores[baseline][name]
        delta = point - opponent if point is not None and opponent is not None else None
        lower = sorted(values)[math.floor(alpha * (len(values) - 1))] if len(values) == iterations else None
        comparisons.setdefault(baseline, {})[name] = {"difference": delta, "lower_bound": lower}
    reasons = []
    answerable = sum(case["answerable"] for case in cases.values())
    negative = len(cases) - answerable
    counts = Counter(case["category"] for case in cases.values() if case["answerable"])
    if answerable < protocol["minimum_answerable"] or negative < protocol["minimum_unanswerable"] or len(clusters) < protocol["minimum_clusters"]:
        reasons.append("insufficient confirmation cases/clusters")
    if any(counts[name] < protocol["minimum_answerable_per_category"] for name in protocol["categories"]):
        reasons.append("insufficient category coverage")
    for name, floor in protocol["minimum_scores"].items():
        if scores[primary][name] is None or scores[primary][name] < floor:
            reasons.append("below absolute floor: " + name)
    if scores[primary]["negative_accuracy"] is None or scores[primary]["negative_accuracy"] < protocol["minimum_negative_accuracy"]:
        reasons.append("negative-case handling below floor")
    for baseline, values in comparisons.items():
        for name, result in values.items():
            if result["difference"] is None or result["difference"] <= 0 or result["lower_bound"] is None or result["lower_bound"] <= 0:
                reasons.append("strict paired superiority unproven: " + baseline + "/" + name)
    status = "diagnostic_only" if bundle["kind"] == "synthetic" else ("fail" if reasons else "pass")
    return {"schema_version": 1, "kind": bundle["kind"], "status": status,
            "source_fingerprint": bundle.get("source_fingerprint"), "case_count": len(cases), "answerable": answerable,
            "negative": negative, "clusters": len(clusters), "repetitions": len(protocol["seeds"]),
            "bootstrap_samples": valid, "comparison_count": len(samples), "metrics": scores,
            "comparisons": comparisons, "gate_reasons": reasons,
            "limits": ["Scoring validated adjudications does not prove annotation independence or run authenticity.", "No conclusion beyond frozen tasks, systems, model and budgets."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--output")
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args()
    try:
        bundle_path = Path(args.bundle).resolve()
        bundle = json.loads(bundle_path.read_text())
        protocol = json.loads((ROOT / "benchmarks/protocol.json").read_text())
        validate_protocol(protocol)
        report = evaluate(bundle, protocol, bundle_path.parent, source_fingerprint(ROOT))
        encoded = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(encoded + "\n")
        print(encoded)
        return 0 if report["status"] == "pass" or (report["status"] == "diagnostic_only" and not args.release) else 1
    except (ValueError, KeyError, TypeError, OSError) as error:
        print("Comparison incomplete/invalid: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
