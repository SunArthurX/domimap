"""CodeGraph 适配器：dist CLI 原生 init/index/explore，逐仓工作副本。

explore 输出 ``路径:行`` 形态（其 CLI 公开输出面），行号剥除后验证存在性；
无法映射的计数入 notes。超时与进程失败分类上抛，不吞。
"""
import os
import re
import shutil
import subprocess
import tempfile

from .base import Adapter
from . import envs

_LOC = re.compile(r"[\w./\\-]+\.[A-Za-z]{1,4}:\d+")
# explore 的公开输出面：**`相对/路径`** 文件头（实测 1.6.2；含中文/空格路径）
_HEADER = re.compile(r"\*\*`([^`\n]+)`\*\*")


class CodegraphAdapter(Adapter):
    name = "codegraph"

    def __init__(self, artifact_dir, env=None):
        super().__init__(artifact_dir)
        self.env = env or envs.codegraph_env()
        if not self.env["available"]:
            raise EnvironmentError("codegraph unavailable: %s" % self.env.get("reason"))
        self.workdir = tempfile.mkdtemp(prefix="dm-adapter-cg-")
        self.repodir = {}

    def _run(self, args, cwd, timeout):
        return subprocess.run(["node", self.env["path"], *args], cwd=cwd,
                              capture_output=True, text=True, timeout=timeout)

    def _prepare_repo(self, repo, budget):
        dest = os.path.join(self.workdir, repo.name)
        if os.path.exists(dest):
            shutil.rmtree(dest)
        shutil.copytree(repo.root, dest, ignore_dangling_symlinks=True)
        prepare_timeout = float(budget.get("prepare_timeout", 900))
        init = self._run(["init"], dest, prepare_timeout)
        if init.returncode != 0:
            raise RuntimeError("codegraph init exit %d: %s"
                               % (init.returncode, init.stderr.strip()[:200]))
        index = self._run(["index", "."], dest, prepare_timeout)
        if index.returncode != 0:
            raise RuntimeError("codegraph index exit %d: %s"
                               % (index.returncode, index.stderr.strip()[:200]))
        self.repodir[repo.name] = dest
        return {"mode": "codegraph init+index（原生）",
                "version_evidence": self.env.get("version_evidence")}

    def _query_repo(self, repo, text, budget):
        timeout = float(budget.get("query_timeout", 60))
        try:
            result = self._run(["explore", text], self.repodir[repo.name], timeout)
        except subprocess.TimeoutExpired:
            raise TimeoutError("codegraph explore timeout >%ss" % timeout)
        if result.returncode != 0:
            raise RuntimeError("codegraph explore exit %d: %s"
                               % (result.returncode, result.stderr.strip()[:200]))
        dest = self.repodir[repo.name]
        paths, notes = [], []
        unmapped = 0
        raw_tokens = [t for t in _HEADER.findall(result.stdout)]
        for token in _LOC.findall(result.stdout):
            raw_tokens.append(token.rsplit(":", 1)[0])
        for candidate in raw_tokens:
            candidate = candidate.replace("\\", "/")
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
