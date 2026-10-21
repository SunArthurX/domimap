"""domimap 适配器：原生多仓聚合图（batch.build_many → Searcher 单次全局查询）。

聚合全局排序即 domimap 的原生多仓语义；仓归属从节点 ID 的服务标签解析，
无法归属的路径保留原样并计入 notes（不猜映射）。
"""
import os
import sys

from .base import (ADAPTER_ERROR, OK, PRODUCT_EMPTY, PRODUCT_ERROR, Adapter,
                   QueryRecord, new_run_id)
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class DomimapAdapter(Adapter):
    name = "domimap"
    version = "source-tree"

    def __init__(self, artifact_dir):
        super().__init__(artifact_dir)
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        self.graph_dir = os.path.join(artifact_dir, "domimap-idx")
        self.searcher = None
        self.seeds = None
        self._repo_files = {}

    def _prepare_repo(self, repo, budget):
        return {}

    def prepare(self, repos, budget=None):
        report = super().prepare(repos, budget)
        if self.ready_repos:
            from domimap import batch
            from domimap.graph import load_seeds
            from domimap.search import Searcher
            roots = [r.root for r in self.ready_repos]
            g, coverage, results = batch.build_many(roots, self.graph_dir)
            self.searcher = Searcher(g)
            from domimap.knowledge import attach_if_present
            attach_if_present(self.searcher, os.path.join(self.graph_dir, "graph.json"))
            self.seeds = load_seeds(os.path.join(ROOT, "domimap", "seeds.json"))
            self._repo_files = {r.name: set() for r in self.ready_repos}
            for r in self.ready_repos:
                for dirpath, _dirnames, filenames in os.walk(r.root):
                    for fn in filenames:
                        rel = os.path.relpath(os.path.join(dirpath, fn), r.root)
                        self._repo_files[r.name].add(rel)
            report.accounting["__aggregate__"] = {
                "graph": "multi-repo merged (batch.build_many)",
                "files_scanned": coverage.get("files_scanned"),
                "per_repo_build": [list(t) for t in results],
            }
        return report

    def _attribute(self, node):
        """节点 → 仓名；优先 ID 服务标签，回退文件路径集合查找。"""
        repo_names = set(self._repo_files)
        parts = node.get("id", "").split(":")
        if len(parts) > 1 and parts[1] in repo_names:
            return parts[1]
        rel = (node.get("file") or "").strip("/")
        for name, files in self._repo_files.items():
            if rel in files:
                return name
        return None

    def query(self, question_id, text, budget=None):
        if self.searcher is None:
            return QueryRecord(new_run_id(), question_id, self.name, time.time(), time.time(),
                               ADAPTER_ERROR, notes=["query_before_prepare"])
        started, run_id = time.time(), new_run_id()
        try:
            result = self.searcher.query(text, top_k=10, expand=False, seeds=self.seeds)
        except Exception as error:
            return self._record(run_id, question_id, started, PRODUCT_ERROR, [], "",
                                ["%s: %s" % (type(error).__name__, str(error)[:200])])
        mapped, notes = [], []
        if result.get("refused"):
            notes.append("refused")
        for node in result.get("seeds", [])[:10]:
            repo = self._attribute(node)
            rel = node.get("file", "")
            if not rel:
                continue
            path = (repo + "/" + rel.strip("/")) if repo else rel
            if path not in mapped:
                mapped.append(path)
        raw_path = self._dump_raw(run_id, question_id, [[{"global": True,
                                                          "raw": [n.get("file", "") for n in result.get("seeds", [])[:10]]}]])
        return self._record(run_id, question_id, started,
                            OK if mapped else PRODUCT_EMPTY, mapped[:5], raw_path, notes)

    def close_repo(self, repo):
        return None
