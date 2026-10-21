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
# 语料根/外部文档族：自备（env；企业私有或开源语料均可，见 benchmarks/DATA_LAYOUT.md）
WORKSPACE = os.path.expanduser(os.environ.get("DOMIMAP_DEV_CORPUS") or "")
EXTRA_CONFIRM = [os.path.expanduser(p) for p in
                 os.environ.get("DOMIMAP_EXTRA_FAMILIES", "").split(",") if p]
LEGACY_QUESTIONS = os.path.expanduser("~/work/dm-benchmark/questions.json")
SKIP_DIRS = {".git", "node_modules", "target", "build", "__pycache__", ".idea"}
GENERIC_MIN_BYTES = 256  # 小于此视为样板文件，不作内容同一性边
# OS/工具元数据（如 .DS_Store 全机同字节）、标准许可证文本（MIT/Apache 全网同字节）、
# 构建工具包装脚本（mvnw/gradlew 各项目逐字节相同）都会造成系统性假关联，不作边
EDGE_EXCLUDE_BASENAMES = {".ds_store", "thumbs.db", "desktop.ini", "__pycache__",
                          "license", "license.txt", "license.md", "copying", "notice",
                          "copying.txt", "copying.md",
                          "mvnw", "mvnw.cmd", "gradlew", "gradlew.bat"}
# 二进制资源（jar/图标/字体）不是评测的代码/文档内容；vendored 第三方目录同理
BINARY_EXT = {".jar", ".ico", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
              ".woff", ".woff2", ".ttf", ".eot", ".otf", ".svg", ".bin", ".class"}
VENDOR_SEGMENTS = {"bower_components", "vendor", "third_party", "thirdparty", "external"}
GLOBAL_COMMON_FAMILIES = 3  # 同哈希出现于 ≥3 族 → 生态通用样板，不作边
# 显式业务关联（人工证据，GitHub 同作者/同业务线；自动化规则漏检时使用，逐条给理由）
EXPLICIT_ASSOCIATIONS = [
    {"families": ["macrozheng-mall", "macrozheng-mall-swarm", "macrozheng-mall-tiny"],
     "reason": "同一作者(macrozheng)的 mall 业务系统三变体：单体/微服务/精简版，"
               "GitHub 互引、文档共用；自动内容边只检出了 mall↔mall-swarm(408 文件)，"
               "mall-tiny 代码改写后无逐字节相同文件，需人工关联"},
]


def _edge_eligible(item):
    parts = item["path"].split("/")
    if any(part.startswith(".") for part in parts):  # 含 .mvn/.github 等隐藏目录
        return False
    if VENDOR_SEGMENTS & set(parts):
        return False
    name = parts[-1].lower()
    if name in EDGE_EXCLUDE_BASENAMES:
        return False
    if os.path.splitext(name)[1] in BINARY_EXT:
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
    edges = {"content_identity": [], "legacy_question_combo": [],
             "prefix_heuristic": [], "explicit_association": []}
    known = {fam["family"] for fam in families}
    for group in EXPLICIT_ASSOCIATIONS:
        members = sorted(set(group["families"]) & known)
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                edges["explicit_association"].append((members[i], members[j]))
    by_hash = {}
    for fam in families:
        for item in fam["inventory"]:
            if _edge_eligible(item):
                by_hash.setdefault(item["sha256"], []).append(fam["family"])
    for sha, owners in by_hash.items():
        unique = sorted(set(owners))
        if len(unique) >= GLOBAL_COMMON_FAMILIES:
            continue  # 生态通用样板（多族共有），非来源关联
        if len(unique) > 1:  # 同仓内重复内容不产生自环边
            for i in range(len(unique)):
                for j in range(i + 1, len(unique)):
                    edge = (unique[i], unique[j])
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
        if not fam.get("prefix_eligible"):
            continue  # 公共仓首段是组织名（alibaba_/apache_），不是业务关联
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


def build(families_spec, legacy_questions_path=None, confirm_split="confirm-candidate"):
    families = []
    for spec in families_spec:
        items, errors = inventory(spec["root"])
        families.append({"family": spec["family"], "split": spec["split"],
                         "root": spec.get("root", ""),
                         "commit": spec.get("commit"),
                         "exposed": bool(spec.get("exposed", False)),
                         "prefix_eligible": bool(spec.get("prefix_eligible", True)),
                         "files": len(items), "inventory": items,
                         "inventory_errors": errors,
                         "content_sha256": family_signature(items)})
    edges = association_edges(families, legacy_questions_path)
    names = [f["family"] for f in families]
    strict = connected_components(names, [edges["content_identity"],
                                          edges["legacy_question_combo"],
                                          edges["explicit_association"]])
    conservative = connected_components(names, [edges["content_identity"],
                                                 edges["legacy_question_combo"],
                                                 edges["explicit_association"],
                                                 edges["prefix_heuristic"]])
    candidate_names = [f["family"] for f in families if f["split"] == confirm_split]
    cand_strict = connected_components(candidate_names,
                                       [edges["content_identity"],
                                        edges["legacy_question_combo"],
                                        edges["explicit_association"]])
    cand_conservative = connected_components(
        candidate_names, [edges["content_identity"], edges["legacy_question_combo"],
                          edges["explicit_association"], edges["prefix_heuristic"]])
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
              "explicit_association_edges": edges["explicit_association"],
              "strict_clusters": strict, "strict_cluster_count": len(strict),
              "conservative_clusters": conservative,
              "conservative_cluster_count": len(conservative),
              "independence_claim_basis": "conservative（较少簇；前缀启发式并入）",
              "confirm_candidate": {
                  "split": confirm_split,
                  "families": candidate_names,
                  "strict_cluster_count": len(cand_strict),
                  "conservative_cluster_count": len(cand_conservative),
                  "protocol_minimum_clusters": 20,
                  "meets_protocol_minimum": len(cand_conservative) >= 20},
              "note": "组合/同内容/同业务前缀的来源归同簇；独立性声明取保守口径；"
                      "已暴露族（旧 599 题覆盖）不得计入确认候选簇数"}
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


def _git_head(root):
    import subprocess
    try:
        return subprocess.check_output(["git", "-C", root, "rev-parse", "HEAD"],
                                       text=True).strip()
    except (subprocess.CalledProcessError, OSError):
        return None


def main():
    if not WORKSPACE:
        raise SystemExit("DOMIMAP_DEV_CORPUS 未设置：请指向自备语料根目录（见 benchmarks/DATA_LAYOUT.md）")
    # 旧 599 题已覆盖企业语料全部 28 confirm 族 + 4 外部族 → 全部已暴露，只能作 dev/回归资产
    fams = sorted(d for d in os.listdir(WORKSPACE)
                  if os.path.isdir(os.path.join(WORKSPACE, d)) and not d.startswith("."))
    families_spec = [{"family": name, "split": "dev", "exposed": True,
                      "root": os.path.join(WORKSPACE, name)} for name in fams]
    families_spec += [{"family": os.path.basename(os.path.normpath(p)),
                       "split": "dev", "exposed": True, "root": p} for p in EXTRA_CONFIRM]
    # 公共开源语料：未暴露确认候选（题目/gold 属独立评测环境）
    public_root = os.path.expanduser("~/work/dm-corpus-public")
    if os.path.isdir(public_root):
        for name in sorted(d for d in os.listdir(public_root)
                           if os.path.isdir(os.path.join(public_root, d))
                           and not d.startswith(".")):
            families_spec.append({"family": name, "split": "confirm-candidate",
                                  "root": os.path.join(public_root, name),
                                  "commit": _git_head(os.path.join(public_root, name)),
                                  "prefix_eligible": False})
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
    cand = report["confirm_candidate"]
    print("families=%d strict=%d conservative=%d | confirm-candidate: families=%d "
          "clusters=%d meets>=%d: %s | edges=%s" % (
              len(manifest["families"]), report["strict_cluster_count"],
              report["conservative_cluster_count"], len(cand["families"]),
              cand["conservative_cluster_count"], cand["protocol_minimum_clusters"],
              cand["meets_protocol_minimum"], report["edge_counts"]))
    print("→ %s" % OUTDIR)


if __name__ == "__main__":
    main()
