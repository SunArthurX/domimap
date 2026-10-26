"""service — CLI / MCP / UI 共用的应用服务（product#6：查询语义、范围、新鲜度、错误状态三入口一致）。

此前三入口各自装配 Graph/Searcher/seeds、各自硬编码默认参数（UI expand=False、kg_doc_search 8/6000 无 seeds
且不记录）、各自实现热重载（MCP 有、UI 无、CLI 每进程）、影响面预算只在 MCP 执行。本模块是唯一的默认参数与
装配点：入口只做协议映射（exit code / isError / HTTP status），不再持有检索逻辑。
"""
import json
import os

from .graph import Graph, load_seeds
from .search import Searcher

QUERY_DEFAULTS = {"top_k": 6, "expand": True, "budget": 3800, "min_cov": 0.3, "domain": None}
DOC_SEARCH_DEFAULTS = {"top_k": 8, "expand": False, "budget": 6000}  # 文档检索：更宽候选、更大文本预算
IMPACT_DEFAULT_DEPTH = 2
IMPACT_MAX_NODES = 200
IMPACT_MAX_DEPTH = 8
SEEDS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seeds.json")


class ServiceError(ValueError):
    """入口可直接映射的有界错误：code ∈ invalid_params | not_found | unavailable。"""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class AppService:
    def __init__(self, graph_path):
        self.graph_path = os.path.abspath(graph_path)
        self.ws = os.path.dirname(self.graph_path)
        self._sig = None
        self.reload()

    # ---------- 装配与热重载 ----------
    def _signature(self):
        sig = []
        for name in (self.graph_path, os.path.join(self.ws, "knowledge.db"), os.path.join(self.ws, "store.db")):
            try:
                st = os.stat(name)
                sig.append((st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append(None)
        return tuple(sig)

    def reload(self):
        from .knowledge import attach_if_present
        from .store import EvidenceResolver
        self.g = Graph.load(self.graph_path)
        coverage = {}
        cov = os.path.join(self.ws, "coverage.json")
        if os.path.exists(cov):
            try:
                with open(cov, encoding="utf-8") as f:
                    coverage = json.load(f)
            except (OSError, ValueError):
                coverage = {}
        self.s = Searcher(self.g, cache_path=self.graph_path + ".idx.json", coverage=coverage)
        attach_if_present(self.s, self.graph_path)  # 图旁 knowledge.db（人工/LLM 笔记）
        self.seeds = load_seeds(SEEDS_PATH)
        self.resolver = EvidenceResolver.beside(self.graph_path)
        self._sig = self._signature()
        return self

    def refresh(self, force=False):
        """graph.json / knowledge.db / store.db 任一变化即重建；返回是否重建（长驻 MCP/UI 不需重启）。"""
        if force or self._signature() != self._sig:
            self.reload()
            return True
        return False

    # ---------- 查询 ----------
    def query(self, text, entry, **overrides):
        """主查询：三入口同一默认参数 + 同一观测记录。返回 (result, obs)。"""
        from .observation import run_query
        if not isinstance(text, str) or not text.strip():
            raise ServiceError("invalid_params", "空查询")
        params = dict(QUERY_DEFAULTS)
        params.update({k: v for k, v in overrides.items() if v is not None or k == "domain"})
        params["seeds"] = self.seeds
        return run_query(self.graph_path, self.s, text, entry, params)

    def doc_search(self, text, entry, **overrides):
        """文档检索：与主查询同一路径与观测，只是默认 top_k/预算不同。返回 (docs, result, obs)。"""
        params = dict(DOC_SEARCH_DEFAULTS)
        params.update({k: v for k, v in overrides.items() if v is not None})  # None 不得覆盖文档默认
        r, obs = self.query(text, entry, **params)
        docs = [n for n in r["seeds"] if n["kind"] == "Doc"]
        return docs, r, obs

    # ---------- 图 ----------
    def impact(self, symbol, depth=IMPACT_DEFAULT_DEPTH, max_nodes=IMPACT_MAX_NODES):
        """反向影响面：预算在遍历中执行；三入口都拿到同一个 partial/truncated 语义。"""
        if not isinstance(symbol, str) or not symbol.strip():
            raise ServiceError("invalid_params", "符号不能为空")
        try:
            depth = int(depth)
            max_nodes = int(max_nodes)
        except (TypeError, ValueError):
            raise ServiceError("invalid_params", "depth/max_nodes 须为整数")
        if not 0 <= depth <= IMPACT_MAX_DEPTH or not 1 <= max_nodes <= 2000:
            raise ServiceError("invalid_params", "depth 0-%d，max_nodes 1-2000" % IMPACT_MAX_DEPTH)
        start, deps = self.g.impact(symbol, depth, max_nodes=max_nodes + 1)
        if not start:
            raise ServiceError("not_found", "无匹配符号")
        partial = len(deps) > max_nodes
        deps = deps[:max_nodes]
        return {"start": start, "deps": deps, "total": len(deps), "partial": partial,
                "truncated": partial, "max_nodes": max_nodes, "depth": depth}

    def domain_map(self):
        return self.g.domain_map()

    # ---------- 证据 ----------
    def evidence_for(self, node):
        return self.resolver.for_node(node)

    def read_evidence(self, ev_id):
        from .store import EvidenceStore
        db = os.path.join(self.ws, "store.db")
        if not os.path.exists(db):
            return {"available": False, "reason": "无证据库（先 build 工作区）"}
        store = EvidenceStore(db)
        try:
            return store.read_evidence(ev_id)  # None = 无此 ID；dict.available=False = 已登记但不可用
        finally:
            store.close()
