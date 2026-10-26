"""context — F3 可信上下文加载：AGENTS.md / SOUL.md 只从显式登记的可信根读取。

- 信任必须显式：`trusted` 为登记根列表，root 不在其中（含 symlink 解析后越界）→ PermissionError；
  没有"默认信任传入的 root"。普通摄入（语料目录）里的同名规则文件只是来源资料（R08：不扩权限）。
- 嵌套作用域：同一根内多层 AGENTS.md/SOUL.md 都列出（各带 sha256/size），但只有"任务范围 scope 向上最近的一层"
  生效（effective），不拼接全部规则；scope 为根内相对目录，None=根。
- 预算超限显式 truncated + dropped 清单（不静默截断）；生效条目优先保留。
"""
import hashlib
import os

RULE_FILES = ("AGENTS.md", "SOUL.md")
DEFAULT_BUDGET = 8000


def _inside(real_root, path):
    real = os.path.realpath(path)
    return real == real_root or real.startswith(real_root + os.sep)


def _scope_dir(real_root, scope):
    if not scope:
        return real_root
    target = os.path.realpath(os.path.join(real_root, scope))
    if not _inside(real_root, target):
        raise PermissionError("任务范围越出可信根：%s" % scope)
    return target


def load_context(root, trusted=None, budget=DEFAULT_BUDGET, scope=None):
    """加载 root 子树（全部深度，跳过隐藏目录）的规则文件；root 必须在 trusted 白名单内。"""
    real = os.path.realpath(root)
    allowed = [os.path.realpath(t) for t in (trusted or [])]
    if not any(_inside(t, real) for t in allowed):
        raise PermissionError("非可信根的规则文件不加载：%s（请先 `domimap trust add`）" % root)
    scope_dir = _scope_dir(real, scope)
    found = []
    for dirpath, dirnames, filenames in os.walk(real):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for fn in filenames:
            if fn in RULE_FILES:
                p = os.path.join(dirpath, fn)
                if os.path.islink(p):
                    continue  # 规则文件不得经链接指向别处
                with open(p, "rb") as f:
                    raw = f.read()
                found.append({"path": os.path.relpath(p, real).replace(os.sep, "/"), "kind": fn,
                              "dir": os.path.realpath(dirpath),
                              "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw),
                              "text": raw.decode("utf-8", errors="replace")})
    found.sort(key=lambda x: x["path"])
    # 生效裁决：每类规则文件取 scope 向上最近的一层（最具体者），其余只列出
    for kind in RULE_FILES:
        candidates = [i for i in found if i["kind"] == kind and _inside(i["dir"], scope_dir)]
        winner = max(candidates, key=lambda i: len(i["dir"])) if candidates else None
        for i in found:
            if i["kind"] == kind:
                i["effective"] = (i is winner)
    for i in found:
        i.pop("dir", None)
    ordered = sorted(found, key=lambda i: (not i["effective"], i["path"]))
    total = sum(i["size"] for i in ordered)
    if total <= budget:
        return {"items": ordered, "truncated": False, "dropped": [], "scope": scope or "",
                "text": render(ordered)}
    keep, used, dropped = [], 0, []
    for i in ordered:  # 超预算：生效条目优先，被丢条目显式列出
        if used + i["size"] <= budget:
            keep.append(i)
            used += i["size"]
        else:
            dropped.append(i["path"])
    return {"items": keep, "truncated": True, "dropped": dropped, "scope": scope or "",
            "text": render(keep)}


def render(items, label=None):
    """生效条目的文本拼接：每条带来源头（根标签/路径/sha 前缀），供入口直接展示或桥接。"""
    blocks = []
    for i in items:
        if not i.get("effective"):
            continue
        head = "## %s%s (sha256 %s)" % ((label + "/") if label else "", i["path"], i["sha256"][:12])
        blocks.append(head + "\n" + i["text"].rstrip() + "\n")
    return "\n".join(blocks)
