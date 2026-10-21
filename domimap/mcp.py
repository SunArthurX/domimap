"""MCP stdio 服务器（newline-delimited JSON-RPC 2.0，零依赖手写协议层）。

工具面遵循方案 §02：单一 kg_explore 主工具 + 4 个辅助。
"""
import json
import os
import sys

TOOLS = [
    {"name": "kg_explore",
     "description": "知识中台主检索：词法种子+图扩展，返回相关 服务/类/方法/路由/表/MQ主题/文档 及关系（Read 等价格式，带置信与出处）",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "自然语言或符号名（支持中文）"},
         "domain": {"type": "string", "description": "可选：限定领域（如 订单域/商品域）"},
         "top_k": {"type": "integer", "default": 6}}},
         "required": ["query"]},
    {"name": "kg_domain_map", "description": "领域地图：域→服务/表/主题/文档 聚合 + 跨域共享表（改动高风险点）",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "kg_impact", "description": "影响面：符号/服务的反向依赖（谁会受影响）",
     "inputSchema": {"type": "object", "properties": {
         "symbol": {"type": "string"}, "depth": {"type": "integer", "default": 2}},
         "required": ["symbol"]}},
    {"name": "kg_doc_search", "description": "文档检索：在 1000+ 项目文档中全文检索",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "kg_read", "description": "按证据 ID 读固化片段（源修改/删除后仍为旧版本）",
     "inputSchema": {"type": "object", "properties": {"ev_id": {"type": "string"}}, "required": ["ev_id"]}},
    {"name": "kg_troubleshoot", "description": "问题排查：症状关键字 → 图+文档双路召回 → 疑点排序（静态边，观测边待接入）",
     "inputSchema": {"type": "object", "properties": {"symptom": {"type": "string"}}, "required": ["symptom"]}},
]

class Server:
    def __init__(self, graph_path):
        self.graph_path = graph_path
        self._mtime = None
        self._reload()

    def _reload(self):
        from .graph import Graph
        from .search import Searcher
        self.g = Graph.load(self.graph_path)
        cov = os.path.join(os.path.dirname(os.path.abspath(self.graph_path)), "coverage.json")
        coverage = {}
        if os.path.exists(cov):
            try:
                import json as _cj
                coverage = _cj.load(open(cov, encoding="utf-8"))
            except Exception:
                coverage = {}
        self.s = Searcher(self.g, cache_path=self.graph_path + ".idx.json", coverage=coverage)
        from .knowledge import attach_if_present
        attach_if_present(self.s, self.graph_path)  # 图旁 knowledge.db（人工/LLM 笔记）
        from .graph import load_seeds
        self.seeds = load_seeds(os.path.join(os.path.dirname(os.path.abspath(__file__)), "seeds.json"))
        try:
            self._mtime = os.stat(self.graph_path).st_mtime_ns
        except OSError:
            self._mtime = None

    def _fresh(self):
        """热重载：graph.json 变化即重建索引（codegraph 新鲜度思想）。"""
        try:
            if os.stat(self.graph_path).st_mtime_ns != self._mtime:
                self._reload()
        except OSError:
            pass

    def _ev_map(self):
        """rel 路径 → 证据 ID（惰性构建，源文件级）。"""
        if getattr(self, "_ev_map_cache", None) is not None:
            return self._ev_map_cache
        out = {}
        db = os.path.join(os.path.dirname(os.path.abspath(self.graph_path)), "store.db")
        if os.path.exists(db):
            from .store import EvidenceStore
            store = EvidenceStore(db)
            for s in store.list_sources():
                out[s["rel"]] = "ev:" + s["sha256"][:20]
            store.close()
        self._ev_map_cache = out
        return out

    def handle(self, name, args):
        """进程内/协议共用的有界入口：非法入参返回结构化错误串，不抛不崩（R08-03）。"""
        try:
            return self._dispatch(name, args if isinstance(args, dict) else {})
        except Exception:
            return "错误: 非法参数（invalid params）"

    def _dispatch(self, name, args):
        self._ev_map_cache = None  # 热重载后失效重建
        self._fresh()
        if name == "kg_explore":
            r = self.s.query(args["query"], top_k=int(args.get("top_k", 6)),
                             domain=args.get("domain"), seeds=self.seeds)
            ev_map = self._ev_map()
            extra = []
            for n in r["seeds"]:
                ev = ev_map.get(n["file"])
                if ev:
                    extra.append("  ev_id=%s  @%s" % (ev, n["file"]))
            if extra:
                return r["text"] + "\n## 证据 ID（kg_read 可读固化片段）\n" + "\n".join(extra[:8])
            return r["text"]
        if name == "kg_read":
            import json as _j
            from .store import EvidenceStore
            db = os.path.join(os.path.dirname(os.path.abspath(self.graph_path)), "store.db")
            if not os.path.exists(db):
                return _j.dumps({"available": False, "reason": "无证据库（先 build 工作区）"}, ensure_ascii=False)
            store = EvidenceStore(db)
            row = store.db.execute("SELECT sid FROM evidence WHERE ev_id=?",
                                   (args["ev_id"],)).fetchone()
            if not row:
                store.close()
                return _j.dumps({"available": False, "reason": "证据 ID 不存在"}, ensure_ascii=False)
            ev = store.evidence_for_source(row[0])
            store.close()
            meta = {k: v for k, v in ev.items() if k != "text"}
            return _j.dumps(meta, ensure_ascii=False) + "\n--- 片段 ---\n" + (ev.get("text") or "")
        if name == "kg_domain_map":
            m = self.g.domain_map()
            lines = []
            for dom, a in sorted(m.items()):
                if dom == "__shared__":
                    continue
                lines.append("【%s】服务:%s | 表:%s | 主题:%s | 文档:%d" %
                             (dom, ",".join(a["services"][:8]) or "-", ",".join(a["tables"][:8]) or "-",
                              ",".join(a["topics"][:5]) or "-", a["docs"]))
            sh = m.get("__shared__", {}).get("shared", [])
            if sh:
                lines.append("\n⚠ 跨域共享表（改动高风险）：" +
                             "; ".join("%s ← %s" % (x["table"], "+".join(x["domains"])) for x in sh))
            return "\n".join(lines) or "（空图）"
        if name == "kg_impact":
            import json as _j
            max_nodes = int(args.get("max_nodes", 200))  # 预算在遍历中执行
            start, deps = self.g.impact(args["symbol"], int(args.get("depth", 2)),
                                        max_nodes=max_nodes + 1)
            if not start:
                return "无匹配符号"
            partial = len(deps) > max_nodes
            deps = deps[:max_nodes]
            return _j.dumps({
                "start": ["[%s] %s @%s" % (n["kind"], n["name"], n["file"]) for n in start],
                "deps": ["%s --%s--> %s" % (a["name"], b, c["name"]) for a, b, c in deps[:max_nodes]],
                "total_deps": len(deps), "truncated": max(0, len(deps) - max_nodes),
                "partial": partial}, ensure_ascii=False)
        if name == "kg_doc_search":
            r = self.s.query(args["query"], top_k=8, expand=False, budget=6000)
            docs = [n for n in r["seeds"] if n["kind"] == "Doc"]
            if not docs:
                return "文档无匹配（诚实拒答：不编造）。" + r["text"][:200]
            return "\n".join("- %s @%s" % (d["name"], d["file"]) for d in docs)
        if name == "kg_troubleshoot":
            from .scenario import scenario_trb
            return scenario_trb(self.g, self.s, args["symptom"])
        raise ValueError("unknown tool " + name)

def serve(graph_path):
    srv = Server(graph_path)
    def send(obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if len(line) > (1 << 20):  # R08-03：超大请求有界错误，不解析不崩溃
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32600,
                                                          "message": "request too large"}})
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            continue
        method = req.get("method")
        rid = req.get("id")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "domimap", "version": "0.4.0"}}})
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            try:
                p = req.get("params", {})
                if not isinstance(p, dict):
                    raise TypeError("params 必须为对象")
                text = srv.handle(p.get("name", ""), p.get("arguments", {}))
                send({"jsonrpc": "2.0", "id": rid, "result": {
                    "content": [{"type": "text", "text": text}],
                    "isError": False}})
            except Exception:
                # R08-03：有界结构化错误，不泄漏内部异常文本（D2 残留收口）
                send({"jsonrpc": "2.0", "id": rid, "result": {
                    "content": [{"type": "text", "text": "错误: 非法参数（invalid params）"}], "isError": True}})
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": rid, "result": {}})
        elif rid is not None:
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "method not found: " + str(method)}})
