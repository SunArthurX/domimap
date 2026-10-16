"""source — 显式来源身份层（R01 最小实装）。

三分离：逻辑身份（sid = repo|rel）、物理路径（可重绑）、内容版本（捕获字节 sha256）。
登记根之外的路径（含 symlink 解析后越界）一律 OutOfRootError；扫描层另有独立防护并记录 coverage。
"""
import hashlib
import json
import os
from types import SimpleNamespace


class OutOfRootError(ValueError):
    """路径（含 symlink 解析后）不在登记根内。"""


class SourceRegistry:
    def __init__(self, root):
        self.root = os.path.realpath(root)
        self.repos = {}    # rid -> {label, path}
        self.sources = {}  # sid -> SimpleNamespace(sid, repo, rel, sha256, size)

    # ---- 登记根（repo） ----
    def register_root(self, repo_path, label=None):
        label = label or os.path.basename(os.path.abspath(repo_path))
        rid = "repo:" + label
        self.repos[rid] = {"label": label, "path": os.path.abspath(repo_path)}
        return rid

    def rebind(self, rid, new_repo_path):
        """来源根移动后的显式重绑：只改物理绑定，逻辑身份（sid）不变（AC-R01-02）。"""
        if rid not in self.repos:
            raise KeyError("未登记的 repo: %s" % rid)
        self.repos[rid]["path"] = os.path.abspath(new_repo_path)

    # ---- 边界 ----
    def _inside(self, path):
        real = os.path.realpath(path)
        if real == self.root or real.startswith(self.root + os.sep):
            return real
        raise OutOfRootError("path escapes registry root: %s -> %s" % (path, real))

    # ---- 登记来源：捕获字节即哈希（同份字节复用，不做二次读取） ----
    def register(self, rid, path):
        real = self._inside(path)
        h = hashlib.sha256()
        size = 0
        with open(real, "rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                h.update(block)
                size += len(block)
        rel = os.path.relpath(real, self.root)
        sid = "%s|%s" % (rid, rel)
        rec = SimpleNamespace(sid=sid, repo=rid, rel=rel, sha256=h.hexdigest(), size=size)
        self.sources[sid] = rec
        return rec

    # ---- 持久化（逻辑 ID 稳定；路径可重绑由调用方更新 repos[path]） ----
    def save(self, db_path):
        d = {"schema": "domimap.source.v1", "root": self.root,
             "repos": self.repos,
             "sources": {sid: vars(r) for sid, r in self.sources.items()}}
        tmp = db_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, db_path)

    @classmethod
    def load(cls, db_path):
        with open(db_path, encoding="utf-8") as f:
            d = json.load(f)
        reg = cls(d["root"])
        reg.repos = d["repos"]
        reg.sources = {sid: SimpleNamespace(**rec) for sid, rec in d["sources"].items()}
        return reg
