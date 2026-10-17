"""claude-obsidian 适配器：vault 摄入（setup-retrieve）+ 核心检索（retrieve.py）。

诊断轨直调其 Compound Vault 检索核心（BM25-only，确定性）；原生完整形态为
宿主 Skill 会话（主轨待模型凭据）。与旧适配器的差别：所有截断逐仓公开记账。
"""
import json
import os
import shutil
import subprocess
import tempfile

from .base import Adapter
from . import envs


class ClaudeObsidianAdapter(Adapter):
    name = "claude_obsidian"

    def __init__(self, artifact_dir, env=None):
        super().__init__(artifact_dir)
        self.env = env or envs.claude_obsidian_env()
        if not self.env["available"]:
            raise EnvironmentError("claude-obsidian unavailable: %s" % self.env.get("reason"))
        self.repo = self.env["path"]
        self.setup = os.path.join(self.repo, "scripts", "setup-retrieve.sh")
        self.retrieve = os.path.join(self.repo, "scripts", "retrieve.py")
        self.workdir = tempfile.mkdtemp(prefix="dm-adapter-co-")
        self.vault = {}

    def _prepare_repo(self, repo, budget):
        vault = os.path.join(self.workdir, repo.name)
        wiki = os.path.join(vault, "wiki", repo.name)
        os.makedirs(wiki, exist_ok=True)
        page_cap = int(budget.get("co_page_cap", 800))
        size_cap = int(budget.get("co_file_size_cap", 400000))
        pages, oversize, bytes_total = [], [], 0
        for dirpath, dirnames, filenames in os.walk(repo.root):
            dirnames[:] = [d for d in dirnames
                           if d not in {".git", "node_modules", "target", "build",
                                        "__pycache__", ".idea"}]
            for fn in filenames:
                src = os.path.join(dirpath, fn)
                rel = os.path.relpath(src, repo.root)
                try:
                    if os.path.getsize(src) >= size_cap:
                        oversize.append(rel)
                        continue
                    dst = os.path.join(wiki, rel.replace("/", "__") + ".md")
                    shutil.copyfile(src, dst, follow_symlinks=False)
                    pages.append(rel)
                    bytes_total += os.path.getsize(src)
                except OSError as error:
                    oversize.append("%s (copy error: %s)" % (rel, error))
        # 页数截断：确定性按路径序；截断明细入 accounting（不再静默）
        pages.sort()
        excluded = pages[page_cap:]
        for rel in excluded:
            os.remove(os.path.join(wiki, rel.replace("/", "__") + ".md"))
        prepare_timeout = float(budget.get("prepare_timeout", 900))
        result = subprocess.run(["bash", self.setup, "--vault", vault, "--apply"],
                                cwd=self.repo, capture_output=True, text=True,
                                timeout=prepare_timeout)
        if result.returncode != 0:
            raise RuntimeError("setup-retrieve exit %d: %s"
                               % (result.returncode, result.stderr.strip()[:200]))
        self.vault[repo.name] = vault
        return {"mode": "setup-retrieve + retrieve.py --no-rerank（BM25-only 确定性诊断轨）",
                "version_evidence": self.env.get("version_evidence"),
                "pages_indexed": len(pages) - len(excluded),
                "pages_exceeded_cap": len(excluded),
                "excluded_by_page_cap": excluded[:50],
                "files_skipped_oversize": oversize[:50],
                "oversize_count": len(oversize),
                "bytes_total": bytes_total}

    def _query_repo(self, repo, text, budget):
        timeout = float(budget.get("query_timeout", 120))
        try:
            result = subprocess.run(
                ["python3", self.retrieve, "--vault", self.vault[repo.name], text, "--no-rerank"],
                cwd=self.repo, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise TimeoutError("retrieve timeout >%ss" % timeout)
        paths, notes = [], []
        if result.returncode == 10:
            return [], ["index_absent_exit_10"]
        if result.returncode != 0:
            raise RuntimeError("retrieve exit %d: %s"
                               % (result.returncode, result.stderr.strip()[:200]))
        try:
            payload = json.loads(result.stdout[result.stdout.index("{"):])
        except (ValueError, IndexError):
            raise RuntimeError("retrieve stdout not JSON: %r" % result.stdout[:120])
        for candidate in payload.get("candidates", []):
            page = candidate.get("page_path", "")
            name = os.path.basename(page)
            if name.endswith(".md"):
                name = name[:-3]
            rel = name.replace("__", "/")
            if not rel:
                continue
            mapped = repo.name + "/" + rel
            if mapped not in paths:
                paths.append(mapped)
        return paths, notes

    def close_repo(self, repo):
        try:
            shutil.rmtree(self.workdir, ignore_errors=True)
        except OSError:
            pass
        return None
