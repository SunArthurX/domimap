"""context — F3 可信上下文加载：AGENTS.md/SOUL.md 只从可信根读取。

普通摄入（语料目录）的规则文件不得升级为指令（R08：不扩权限）；每条带 sha256/size；
预算超限显式 truncated + dropped 清单（不静默截断）。
"""
import hashlib
import os

RULE_FILES = ("AGENTS.md", "SOUL.md")


def load_context(root, trusted=None, budget=8000):
    """加载 root 下（含一层嵌套目录）的规则文件。root 不在 trusted 白名单 → PermissionError。"""
    real = os.path.realpath(root)
    allowed = [os.path.realpath(t) for t in (trusted or [root])]
    if not any(real == t or real.startswith(t + os.sep) for t in allowed):
        raise PermissionError("非可信根的规则文件不加载：%s" % root)
    found = []
    for dirpath, dirnames, filenames in os.walk(real):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if fn in RULE_FILES:
                p = os.path.join(dirpath, fn)
                raw = open(p, "rb").read()
                found.append({"path": os.path.relpath(p, real), "sha256": hashlib.sha256(raw).hexdigest(),
                              "size": len(raw), "text": raw.decode("utf-8", errors="replace")})
    found.sort(key=lambda x: x["path"])
    total = sum(i["size"] for i in found)
    if total <= budget:
        return {"items": found, "truncated": False, "dropped": []}
    keep, used, dropped = [], 0, []
    for i in found:  # 超预算：保留先序条目，被丢条目显式列出
        if used + i["size"] <= budget:
            keep.append(i); used += i["size"]
        else:
            dropped.append(i["path"])
    return {"items": keep, "truncated": True, "dropped": dropped}
