"""Graphify 适配器：venv CLI 原生建图/查询（update + query），逐仓工作副本。

输出从展示文本抽取 ``src=`` 路径（其 CLI 的公开输出面），逐 token 验证存在性；
无法映射的计数入 notes。超时与进程失败分类上抛，不吞。
"""
import os
import re
import shutil
import subprocess
import tempfile

from .base import Adapter
from . import envs

_SRC = re.compile(r"src=(\S+)")


class GraphifyAdapter(Adapter):
    name = "graphify"

    def __init__(self, artifact_dir, env=None):
        super().__init__(artifact_dir)
        self.env = env or envs.graphify_env()
        if not self.env["available"]:
            raise EnvironmentError("graphify unavailable: %s" % self.env.get("reason"))
        self.workdir = tempfile.mkdtemp(prefix="dm-adapter-gf-")
        self.repodir = {}

    def _prepare_repo(self, repo, budget):
        dest = os.path.join(self.workdir, repo.name)
        if os.path.exists(dest):
            shutil.rmtree(dest)
        shutil.copytree(repo.root, dest, ignore_dangling_symlinks=True)
        build_timeout = float(budget.get("prepare_timeout", 900))
        result = subprocess.run([self.env["path"], "update", "."], cwd=dest,
                                capture_output=True, text=True, timeout=build_timeout)
        if result.returncode != 0:
            raise RuntimeError("graphify update exit %d: %s"
                               % (result.returncode, result.stderr.strip()[:200]))
        self.repodir[repo.name] = dest
        return {"mode": "graphify update（原生建图）",
                "version_evidence": self.env.get("version_evidence"),
                "build_stdout_tail": result.stdout.strip()[-200:]}

    def _query_repo(self, repo, text, budget):
        timeout = float(budget.get("query_timeout", 60))
        try:
            result = subprocess.run([self.env["path"], "query", text],
                                    cwd=self.repodir[repo.name],
                                    capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise TimeoutError("graphify query timeout >%ss" % timeout)
        # 其原生空结果语义：exit 4 + "No matching nodes found."（实测 cli 源码 sys.exit(1/2) 为错误）
        if result.returncode == 4 and "No matching nodes found" in result.stdout:
            return [], ["no_matching_nodes"]
        if result.returncode != 0:
            raise RuntimeError("graphify query exit %d: %s"
                               % (result.returncode, result.stderr.strip()[:200]))
        dest = self.repodir[repo.name]
        paths, notes = [], []
        unmapped = 0
        for token in _SRC.findall(result.stdout):
            candidate = token.replace("\\", "/").rstrip(".,;)")
            if candidate.startswith(dest):
                rel = os.path.relpath(candidate, dest)
            elif os.path.exists(os.path.join(dest, candidate)):
                rel = candidate
            else:
                unmapped += 1
                continue
            mapped = repo.name + "/" + rel
            if mapped not in paths:
                paths.append(mapped)
        if unmapped:
            notes.append("unmapped_tokens=%d" % unmapped)
        return paths, notes

    def close_repo(self, repo):
        try:
            shutil.rmtree(self.workdir, ignore_errors=True)
        except OSError:
            pass
        return None
