#!/usr/bin/env python3
"""M5 语料冻结清单：以 DOMIMAP_DEV_CORPUS 指向的企业语料各仓为独立来源族，dev/confirm 按族隔离分片。

输出 out/benchmark/corpus-manifest.json：族名/分片/文件数/内容摘要（无正文）。
确认侧 gold 不在本仓库生成（独立环境）；本清单只登记族与分片。
"""
import hashlib
import json
import os
import sys

# 语料根/外部文档族：自备（env；企业私有或开源语料均可，见 benchmarks/DATA_LAYOUT.md）
WORKSPACE = os.path.expanduser(os.environ.get("DOMIMAP_DEV_CORPUS") or "")
if not WORKSPACE:
    raise SystemExit("DOMIMAP_DEV_CORPUS 未设置：请指向自备语料根目录")
# 文档丰富的外部来源族（补 document_reasoning 类配额；刻意排除业务目录，遵守用户边界）
EXTRA_CONFIRM = [os.path.expanduser(p) for p in
                 os.environ.get("DOMIMAP_EXTRA_FAMILIES", "").split(",") if p]
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "out", "benchmark", "corpus-manifest.json")
DEV_FAMILIES = 20  # 其余入 confirm（≥25），族级隔离


def family_signature(root):
    """族内容摘要：文件清单相对路径 + 大小的有序哈希（无正文，可审计）。"""
    items = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in
                       {".git", "node_modules", "target", "build", "__pycache__"}]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            try:
                items.append((os.path.relpath(p, root).replace("\\", "/"), os.path.getsize(p)))
            except OSError:
                pass
    items.sort()
    h = hashlib.sha256("\n".join("%s %d" % x for x in items).encode()).hexdigest()
    return h, len(items)


def main():
    fams = sorted(d for d in os.listdir(WORKSPACE)
                  if os.path.isdir(os.path.join(WORKSPACE, d)) and not d.startswith("."))
    extra = [os.path.basename(os.path.normpath(p)) for p in EXTRA_CONFIRM]
    rows = []
    for i, name in enumerate(fams):
        sig, files = family_signature(os.path.join(WORKSPACE, name))
        rows.append({"family": name,
                     "split": "dev" if i < DEV_FAMILIES else "confirm",
                     "files": files, "content_sha256": sig})
    for name, root in zip(extra, EXTRA_CONFIRM):
        sig, files = family_signature(root)
        rows.append({"family": name, "split": "confirm",
                     "files": files, "content_sha256": sig, "root": root})
    dev = [r for r in rows if r["split"] == "dev"]
    conf = [r for r in rows if r["split"] == "confirm"]
    manifest = {"schema": "domimap.corpus.v1", "workspace": WORKSPACE,
                "families": rows, "dev_count": len(dev), "confirm_count": len(conf),
                "note": "族级隔离；confirm 族 gold 在独立环境标注，不进实现目录"}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(manifest, open(OUT, "w"), ensure_ascii=False, indent=1)
    print("dev=%d confirm=%d total=%d → %s" % (len(dev), len(conf), len(rows), OUT))


if __name__ == "__main__":
    main()
