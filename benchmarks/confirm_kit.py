#!/usr/bin/env python3
"""确认执行套件（confirmation kit）：移交独立保管人的自包含工件包。

按计划 §11.3，独立评测环境需包含：
  corpus/（只读快照+哈希）、private/（题目/gold）、sandbox/、runs/、judgments/、bundle/、reports/
本脚本生成可移交的执行包骨架 + 全部命令行说明书。独立保管人在独立机器上：
  1. 运行本脚本生成 corpus manifest（从 ~/work/dm-corpus-public 或指定路径）
  2. 用 generate_questions_v2.py 语义生成 480 题（gold 双标由两位独立标注者完成）
  3. 预登记封存（preregistration-draft 模板已提供）
  4. 执行五系统 × 480 题 × 5 次主轨（runner 命令见下）
  5. 盲评/仲裁 → bundle → release-check

用法（独立环境内）：
  python3 confirm_kit.py init --corpus-root <路径> --out <batch_id>
  python3 confirm_kit.py questions --batch <batch_id>   # 生成题目集草案
  python3 confirm_kit.py run --batch <batch_id> --system <name> --repeats 5
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def init(corpus_root, batch_id, out_root="confirm"):
    """初始化独立环境工件布局 + 语料内容清单。"""
    out = os.path.join(out_root, batch_id)
    for sub in ("corpus", "private", "sandbox", "runs", "judgments", "bundle", "reports"):
        os.makedirs(os.path.join(out, sub), exist_ok=True)
    manifest = {"schema": "domimap.confirm-corpus.v1",
                "batch_id": batch_id,
                "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "families": []}
    for name in sorted(os.listdir(corpus_root)):
        root = os.path.join(corpus_root, name)
        if not os.path.isdir(root) or name.startswith("."):
            continue
        files = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in
                           {".git", "node_modules", "target", "build", "__pycache__"}]
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                files.append({"path": os.path.relpath(p, root),
                              "size": os.path.getsize(p), "sha256": _sha(p)})
        files.sort(key=lambda x: x["path"])
        h = hashlib.sha256()
        for item in files:
            h.update(("%s %d %s\n" % (item["path"], item["size"],
                                      item["sha256"])).encode())
        commit = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"],
                                capture_output=True, text=True).stdout.strip()
        manifest["families"].append({"family": name, "root": root,
                                     "commit": commit or None,
                                     "files": len(files), "content_sha256": h.hexdigest()})
    mpath = os.path.join(out, "corpus", "manifest.json")
    json.dump(manifest, open(mpath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("families=%d → %s" % (len(manifest["families"]), mpath))
    _write_readme(out, batch_id, manifest)
    _write_prereg(out, batch_id, manifest)
    return out


def _write_readme(out, batch_id, manifest):
    clusters = len(manifest["families"])
    readme = """# 确认执行套件：%s

## 独立环境检查清单
1. 本目录在独立机器/账号上（与实现会话物理隔离）。
2. 语料 manifest 已核对（%d 族，逐文件 SHA-256）。
3. 题目/gold 由两位独立标注者完成（不经 domimap 管线，不用本工具生成 gold）。

## 执行步骤
```bash
# 1. 生成题目草案（标注者在此基础上双标 gold）
python3 -B benchmarks/corpus/generate_questions_v2.py  # 参考；gold 必须独立双标

# 2. 预登记封存（填入 sealed_by/sealed_at 后不可改）
#    编辑 preregistration.json → 填 sealed_by（保管人名）

# 3. 五系统 × 480 题 × 5 次主轨（每次启用一个产品）
for sys in domimap claude_obsidian codebase_memory_mcp codegraph graphify; do
  for rep in 11 23 37 53 71; do
    python3 -B benchmarks/runners/confirm_batch.py \\
      --batch %s --system $sys --repeat $rep
  done
done

# 4. 盲评/仲裁 → bundle → release-check（独立环境内执行）
```

## 关键约束（不可违反）
- gold 不经产品管线；标注者不知道系统身份（匿名 A-E）。
- 预算/token/工具调用逐题记录（runner 自动）。
- 确认后不得对该批明细调参；需改进时该批转为已暴露回归集。
""" % (batch_id, clusters, batch_id)
    open(os.path.join(out, "README.md"), "w", encoding="utf-8").write(readme)


def _write_prereg(out, batch_id, manifest):
    prereg = {"schema": "domimap.preregistration.v1",
              "batch_id": batch_id,
              "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "corpus_manifest_sha256": _sha(os.path.join(out, "corpus", "manifest.json")),
              "protocol_sha256": _sha(os.path.join(ROOT, "benchmarks", "protocol.json")),
              "candidate": {"git_head": subprocess.run(
                  ["git", "-C", ROOT, "rev-parse", "HEAD"],
                  capture_output=True, text=True).stdout.strip()},
              "planned_scale": {"questions": 480, "systems": 5, "repeats": 5},
              "sealed_by": None, "sealed_at": None,
              "note": "独立保管人填 sealed_by/sealed_at 后封存"}
    json.dump(prereg, open(os.path.join(out, "preregistration.json"), "w",
                           encoding="utf-8"), ensure_ascii=False, indent=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd")
    p_init = sub.add_parser("init")
    p_init.add_argument("--corpus-root", required=True)
    p_init.add_argument("--batch-id", default=None)
    p_init.add_argument("--out-root", default="confirm")
    args = parser.parse_args()
    if args.cmd == "init":
        batch_id = args.batch_id or ("confirm-%s" % uuid.uuid4().hex[:8])
        init(os.path.expanduser(args.corpus_root), batch_id, args.out_root)


if __name__ == "__main__":
    main()
