#!/usr/bin/env python3
"""AC-R12-01：十条真实任务回放——每条记录依据时间/Top5/适用判断/失败分类。

表任务可自动核验（gold=图上读写该表的源文件集）；中文/服务任务人工判断（记录在 log 注释列）。
"""
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
G = os.path.join(ROOT, "out", "dev-corp-dev", "graph.json")

def main():
    spec = json.load(open(os.path.join(os.path.dirname(__file__), "tasks.json"), encoding="utf-8"))
    rows = []
    for t in spec["tasks"]:
        t0 = time.time()
        p = subprocess.run([sys.executable, "-B", "-m", "domimap", "query", t["query"], "-g", G],
                           cwd=ROOT, capture_output=True, text=True)
        dt = time.time() - t0
        files = []
        for m in re.findall(r"@\s*(\S+)", p.stdout):
            if m not in files:
                files.append(m)
        top5 = files[:5]
        if t["check"] == "auto":
            hit = any(any(g.endswith(x) or x.endswith(g) for g in t["gold_paths"]) for x in top5)
            applic = "适用" if hit else "未命中"
        else:
            applic = "人工复核见 log"
        fail = "拒答" if p.returncode == 3 else ("空" if not top5 else "-")
        rows.append({"id": t["id"], "query": t["query"], "secs": round(dt, 2),
                     "top5": top5[:3], "applicability": applic, "failure": fail})
        print(json.dumps(rows[-1], ensure_ascii=False))
    auto = [r for r in rows if r["applicability"] != "人工复核见 log"]
    rate = sum(1 for r in auto if r["applicability"] == "适用") / len(auto) if auto else 0
    print("[real-tasks] 自动核验命中率 %.0f%% (%d/%d)；中位耗时 %.2fs" % (
        rate * 100, sum(1 for r in auto if r["applicability"] == "适用"), len(auto),
        sorted(r["secs"] for r in rows)[len(rows) // 2]))

if __name__ == "__main__":
    main()
