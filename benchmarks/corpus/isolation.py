#!/usr/bin/env python3
"""数据隔离层 v2：逐文件内容清单 + 来源关联簇 + 预登记草案。

修复两个审计缺陷（specs/tasks/comparison-dataset-isolation.md）：
- P1：族摘要从"路径+大小"改为逐文件字节 SHA-256（同大小改内容必可检出）。
- P0：组合簇不算独立族——按来源关联图连通分量聚类；独立性声明取保守口径
  （含启发式边的较少簇数），两个口径都进报告。

dev 可见产物：out/benchmark/{corpus-manifest-v2,cluster-report,preregistration-draft}.json。
确认侧题目/gold 属独立评测环境（缺位如实登记，不在此生成）。
"""
import hashlib
import json
import os
import re
import sys
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTDIR = os.path.join(ROOT, "out", "benchmark")
WORKSPACE = os.path.expanduser("~/work/dev-corpus")
EXTRA_CONFIRM = [os.path.expanduser(p) for p in (
    "EXTERNAL_FAMILY_PATH",
    "EXTERNAL_FAMILY_PATH",
    "EXTERNAL_FAMILY_PATH",
    "EXTERNAL_FAMILY_PATH")]
LEGACY_QUESTIONS = os.path.expanduser("~/work/dm-benchmark/questions.json")
DEV_FAMILIES = 20
SKIP_DIRS = {".git", "node_modules", "target", "build", "__pycache__", ".idea"}
GENERIC_MIN_BYTES = 256  # 小于此视为样板文件，不作内容同一性边
# OS/工具元数据（如 .DS_Store 全机同字节）会造成系统性假关联，不作边
EDGE_EXCLUDE_BASENAMES = {".ds_store", "thumbs.db", "desktop.ini", "__pycache__"}


def _edge_eligible(item):
    name = os.path.basename(item["path"]).lower()
    if name in EDGE_EXCLUDE_BASENAMES or name.startswith("."):
        return False
    return item["size"] >= GENERIC_MIN_BYTES


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory(root):
    """逐文件 (relpath, size, sha256) 清单；不可读文件记入 errors。"""
    items, errors = [], []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, root).replace("\\", "/")
            try:
                size = os.path.getsize(path)
                items.append({"path": rel, "size": size, "sha256": file_sha256(path)})
            except OSError as error:
                errors.append({"path": rel, "error": str(error)[:120]})
    items.sort(key=lambda x: x["path"])
    return items, errors


def family_signature(items):
    """族内容签名：对 (relpath, size, sha256) 有序哈希——同大小改内容必变。"""
    h = hashlib.sha256()
    for item in items:
        h.update(("%s %d %s\n" % (item["path"], item["size"], item["sha256"])).encode("utf-8"))
    return h.hexdigest()


def _first_token(name):
    """业务前缀启发式：首个分隔符前的字母数字段。"""
    token = re.split(r"[-._]", name)[0]
    return token if len(token) >= 4 else None


def association_edges(families, legacy_questions_path=None):
    """来源关联边（dedup、有序对）。三种信号，全部可审计。"""
    edges = {"content_identity": [], "legacy_question_combo": [], "prefix_heuristic": []}
    by_hash = {}
    for fam in families:
        for item in fam["inventory"]:
            if _edge_eligible(item):
                by_hash.setdefault(item["sha256"], []).append(fam["family"])
    for sha, owners in by_hash.items():
        if len(owners) > 1:
            for i in range(len(owners)):
                for j in range(i + 1, len(owners)):
                    edge = tuple(sorted((owners[i], owners[j])))
                    if edge not in edges["content_identity"]:
                        edges["content_identity"].append(edge)
    if legacy_questions_path and os.path.isfile(legacy_questions_path):
        questions = json.load(open(legacy_questions_path, encoding="utf-8"))["questions"]
        for question in questions:
            parts = sorted(set(question.get("family", "").split("+")))
            for i in range(len(parts)):
                for j in range(i + 1, len(parts)):
                    edge = tuple(sorted((parts[i], parts[j])))
                    if edge not in edges["legacy_question_combo"]:
                        edges["legacy_question_combo"].append(edge)
    groups = {}
    for fam in families:
        token = _first_token(fam["family"])
        if token:
            groups.setdefault(token, []).append(fam["family"])
    for members in groups.values():
        if len(members) > 1:
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    edges["prefix_heuristic"].append(tuple(sorted((members[i], members[j]))))
    return edges


def connected_components(names, edge_lists):
    parent = {name: name for name in names}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for edges in edge_lists:
        for a, b in edges:
            if a in parent and b in parent:
                union(a, b)
    clusters = {}
    for name in names:
        clusters.setdefault(find(name), []).append(name)
    return sorted(sorted(members) for members in clusters.values())


def build(families_spec, legacy_questions_path=None):
    families = []
    for spec in families_spec:
        items, errors = inventory(spec["root"])
        families.append({"family": spec["family"], "split": spec["split"],
                         "root": spec.get("root", ""),
                         "files": len(items), "inventory": items,
                         "inventory_errors": errors,
                         "content_sha256": family_signature(items)})
    edges = association_edges(families, legacy_questions_path)
    names = [f["family"] for f in families]
    strict = connected_components(names, [edges["content_identity"],
                                          edges["legacy_question_combo"]])
    conservative = connected_components(names, [edges["content_identity"],
                                                 edges["legacy_question_combo"],
                                                 edges["prefix_heuristic"]])
    manifest = {"schema": "domimap.corpus.v2", "workspace": WORKSPACE,
                "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "families": [
                    {**{k: v for k, v in f.items() if k != "inventory"},
                     "files_inventory": f["inventory"]} for f in families]}
    report = {"schema": "domimap.cluster-report.v1",
              "generated_utc": manifest["generated_utc"],
              "edge_counts": {k: len(v) for k, v in edges.items()},
              "content_identity_edges": edges["content_identity"][:2000],
              "legacy_question_combo_edges": edges["legacy_question_combo"],
              "prefix_heuristic_edges": edges["prefix_heuristic"],
              "strict_clusters": strict, "strict_cluster_count": len(strict),
              "conservative_clusters": conservative,
              "conservative_cluster_count": len(conservative),
              "independence_claim_basis": "conservative（较少簇；前缀启发式并入）",
              "note": "组合/同内容/同业务前缀的来源归同簇；独立性声明取保守口径"}
    return manifest, report


def preregistration_draft(manifest, report, extra_hashes=None):
    def sha_of(path):
        return file_sha256(path) if os.path.isfile(path) else None

    hashes = {
        "corpus_manifest_v2": manifest.get("self_sha256"),
        "cluster_report": report.get("self_sha256"),
        "protocol": sha_of(os.path.join(ROOT, "benchmarks", "protocol.json")),
    }
    hashes.update(extra_hashes or {})
    missing = [k for k, v in hashes.items() if not v]
    if missing:
        raise ValueError("preregistration missing hashes: %s" % missing)
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import check_specs
    return {"schema": "domimap.preregistration.v1",
            "batch_id": "batch-%s" % uuid.uuid4().hex[:12],
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "candidate": {"git_head": os.popen("git -C %s rev-parse HEAD" % ROOT).read().strip(),
                          "source_fingerprint": check_specs.source_fingerprint()},
            "artifact_hashes": hashes,
            "splits": {"dev_families": sorted({f["family"] for f in manifest["families"]
                                               if f["split"] == "dev"}),
                       "confirm_families": sorted({f["family"] for f in manifest["families"]
                                                   if f["split"] == "confirm"})},
            "independent_cluster_count": report["conservative_cluster_count"],
            "sealed_by": None, "sealed_at": None,
            "note": "草案：独立保管人封存前无效；确认题目/gold 在独立评测环境，不在此生成"}


def main():
    fams = sorted(d for d in os.listdir(WORKSPACE)
                  if os.path.isdir(os.path.join(WORKSPACE, d)) and not d.startswith("."))
    families_spec = [{"family": name, "split": "dev" if i < DEV_FAMILIES else "confirm",
                      "root": os.path.join(WORKSPACE, name)}
                     for i, name in enumerate(fams)]
    families_spec += [{"family": os.path.basename(os.path.normpath(p)),
                       "split": "confirm", "root": p} for p in EXTRA_CONFIRM]
    manifest, report = build(families_spec, LEGACY_QUESTIONS)
    os.makedirs(OUTDIR, exist_ok=True)
    mpath = os.path.join(OUTDIR, "corpus-manifest-v2.json")
    rpath = os.path.join(OUTDIR, "cluster-report.json")
    json.dump(manifest, open(mpath, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(report, open(rpath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    manifest["self_sha256"] = file_sha256(mpath)
    report["self_sha256"] = file_sha256(rpath)
    draft = preregistration_draft(manifest, report)
    json.dump(draft, open(os.path.join(OUTDIR, "preregistration-draft.json"), "w",
                          encoding="utf-8"), ensure_ascii=False, indent=1)
    print("families=%d strict_clusters=%d conservative_clusters=%d edges=%s" % (
        len(manifest["families"]), report["strict_cluster_count"],
        report["conservative_cluster_count"], report["edge_counts"]))
    print("→ %s" % OUTDIR)


if __name__ == "__main__":
    main()
