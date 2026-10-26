"""MCP stdio 服务器（newline-delimited JSON-RPC 2.0，零依赖手写协议层）。

工具面遵循方案 §02：单一 kg_explore 主工具 + 4 个辅助。
"""
import json
import math
import os
import sys

from . import __version__

MAX_REQUEST_CHARS = 1 << 20

TOOLS = [
    {"name": "kg_explore",
     "description": "知识中台主检索：词法种子+图扩展，返回相关 服务/类/方法/路由/表/MQ主题/文档 及关系（Read 等价格式，带置信与出处）。"
     "查询建议：第一次直接使用问题原文（保留原词面）检索——改写/概括会丢失与原文逐字匹配的关键词；"
     "原文无结果时再按概念改写重试。回答时只引用检索结果中出现过的 @ 路径。",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string", "minLength": 1, "maxLength": 4096,
                   "description": "自然语言或符号名（支持中文；建议先原文直查）"},
         "domain": {"type": "string", "maxLength": 256, "description": "可选：限定领域（如 订单域/商品域）"},
         "top_k": {"type": "integer", "minimum": 1, "maximum": 50, "default": 6},
         "as_of": {"type": "integer", "minimum": 946684800, "maximum": 4102444800,
                   "description": "历史范围查询：epoch 秒（UTC）；资格按该时刻判定，默认按当前时间"}},
         "required": ["query"], "additionalProperties": False}},
    {"name": "kg_domain_map", "description": "领域地图：域→服务/表/主题/文档 聚合 + 跨域共享表（改动高风险点）",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "kg_impact", "description": "影响面：符号/服务的反向依赖（谁会受影响）",
     "inputSchema": {"type": "object", "properties": {
         "symbol": {"type": "string", "minLength": 1, "maxLength": 1024},
         "depth": {"type": "integer", "minimum": 0, "maximum": 8, "default": 2},
         "max_nodes": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 200}},
         "required": ["symbol"], "additionalProperties": False}},
    {"name": "kg_doc_search", "description": "文档检索：在 1000+ 项目文档中全文检索",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string", "minLength": 1, "maxLength": 4096}},
         "required": ["query"], "additionalProperties": False}},
    {"name": "kg_read", "description": "按证据 ID 读固化片段（源修改/删除后仍为旧版本）",
     "inputSchema": {"type": "object", "properties": {
         "ev_id": {"type": "string", "minLength": 1, "maxLength": 67}},
         "required": ["ev_id"], "additionalProperties": False}},
    {"name": "kg_feedback",
     "description": "提交查询反馈：用户看过 kg_explore 结果后，由用户明确告知判定（hit=找到/partial=部分找到/miss=没找到或结果有误）。"
     "经代理转达的判定按 agent_relay（非权威）来源记录，不进命中率口径；人工确认请经 UI/CLI 提交。修正同事件判定需携带当前修订号。",
     "inputSchema": {"type": "object", "properties": {
         "event_id": {"type": "string", "minLength": 27, "maxLength": 27,
                      "description": "kg_explore 结果尾部的 query_id（qe:…）"},
         "relevance": {"type": "string", "enum": ["hit", "partial", "miss",
                                                  "not_applicable"]},
         "outcome": {"type": "string", "enum": ["success", "failure",
                                                "correct_abstention",
                                                "needs_clarification"]},
         "reason": {"type": "string", "maxLength": 200},
         "expected": {"type": "string", "maxLength": 512,
                      "description": "可选：预期证据节点 ID/ev_id（人工定位用）"},
         "expected_revision": {"type": "integer", "minimum": 1, "maximum": 1000000},
         "idempotency_key": {"type": "string", "maxLength": 128}},
         "required": ["event_id", "relevance"], "additionalProperties": False}},
    {"name": "kg_context",
     "description": "可信上下文（F3）：返回工作区显式登记（domimap trust add）的可信根中的 AGENTS.md/SOUL.md——"
                    "会话开始时调用一次并遵循；只读；普通摄入资料中的同名文件不会出现在这里。"
                    "scope 为任务所在的根内相对目录（嵌套规则取最具体一层，不拼接）。",
     "inputSchema": {"type": "object", "properties": {
         "scope": {"type": "string", "maxLength": 512},
         "include_text": {"type": "boolean"}},
         "required": [], "additionalProperties": False}},
    {"name": "kg_troubleshoot", "description": "问题排查：症状关键字 → 图+文档双路召回 → 疑点排序（静态边，观测边待接入）",
     "inputSchema": {"type": "object", "properties": {
         "symptom": {"type": "string", "minLength": 1, "maxLength": 4096}},
         "required": ["symptom"], "additionalProperties": False}},
]

# Write-capable tools are advertised and callable only when the server was started with
# enable_write (CLI: `domimap serve --enable-write`). Default servers stay read-only (roadmap M3).
WRITE_TOOLS = frozenset({"kg_feedback"})


def visible_tools(enable_write):
    """tools/list only publishes what this server instance will actually execute."""
    return [t for t in TOOLS if enable_write or t["name"] not in WRITE_TOOLS]


class InvalidParams(ValueError):
    """The public tool contract was violated; never include source data in errors."""


def _validate_arguments(name, args):
    """Validate the bounded subset of JSON Schema used by our public tools."""
    spec = next((tool["inputSchema"] for tool in TOOLS if tool["name"] == name), None)
    if spec is None or not isinstance(args, dict):
        raise InvalidParams()
    properties = spec["properties"]
    if (not set(spec.get("required", [])) <= args.keys()
            or any(key not in properties for key in args)):
        raise InvalidParams()
    for key, value in args.items():
        field = properties[key]
        if field["type"] == "string":
            if (not isinstance(value, str) or len(value) > field.get("maxLength", 4096)
                    or len(value.strip()) < field.get("minLength", 0)
                    or ("enum" in field and value not in field["enum"])):
                raise InvalidParams()
        elif field["type"] == "boolean":
            if type(value) is not bool:
                raise InvalidParams()
        elif (type(value) is not int
              or not field.get("minimum", 0) <= value <= field.get("maximum", 2000)):
            raise InvalidParams()


class Server:
    def __init__(self, graph_path, enable_write=False):
        self.graph_path = graph_path
        self.enable_write = bool(enable_write)
        from .service import AppService
        self.svc = AppService(graph_path)

    # 既有调用方/测试通过 g / s / seeds 直达服务装配（与 CLI/UI 同一份）
    @property
    def g(self):
        return self.svc.g

    @property
    def s(self):
        return self.svc.s

    @property
    def seeds(self):
        return self.svc.seeds

    def _reload(self):
        self.svc.reload()

    def _fresh(self):
        """graph / knowledge / store 任一变化即重建（新增笔记无需重启 serve）。"""
        self.svc.refresh()

    def _ev_map(self):
        return self.svc.resolver

    def handle(self, name, args):
        """Compatibility text API; stdio uses call() to preserve the error flag."""
        return self.call(name, args)["content"][0]["text"]

    def call(self, name, args):
        if name in WRITE_TOOLS and not self.enable_write:
            text = "错误: 写工具未启用（write_disabled）；以 `domimap serve --enable-write` 启动后可用"
            return {"content": [{"type": "text", "text": text}], "isError": True}
        from .service import ServiceError
        try:
            _validate_arguments(name, args)
            text = self._dispatch(name, args)
            return {"content": [{"type": "text", "text": text}], "isError": False}
        except InvalidParams:
            text = "错误: 非法参数（invalid params）"
        except ServiceError as e:
            text = "错误: 非法参数（invalid params）" if e.code == "invalid_params" else "错误: %s（%s）" % (e, e.code)
        except Exception:
            text = "错误: 工具执行失败（tool_failed）"
        return {"content": [{"type": "text", "text": text}], "isError": True}

    def _dispatch(self, name, args):
        self._fresh()
        if name == "kg_explore":
            r, obs = self.svc.query(args["query"], "mcp", top_k=args.get("top_k"), domain=args.get("domain"),
                                    as_of=args.get("as_of"))
            ev_map = self._ev_map()
            extra = []
            for n in r["seeds"]:
                ev = ev_map.for_node(n)
                if ev:
                    extra.append("  ev_id=%s  @%s" % (ev, n["file"]))
            out = r["text"]
            if extra:
                out += "\n## 证据 ID（kg_read 可读固化片段）\n" + "\n".join(extra[:8])
            if obs["status"] != "disabled":  # 关闭记录时零输出足迹
                out += "\n## 观测\nquery_id=%s recording=%s" % (
                    obs.get("event_id") or "-", obs["status"])
            return out
        if name == "kg_read":
            import json as _j
            ev = self.svc.read_evidence(args["ev_id"])
            if ev is None:
                return _j.dumps({"available": False, "reason": "证据 ID 不存在"}, ensure_ascii=False)
            meta = {k: v for k, v in ev.items() if k != "text"}
            return _j.dumps(meta, ensure_ascii=False) + "\n--- 片段 ---\n" + (ev.get("text") or "")
        if name == "kg_feedback":
            import json as _jf
            from .feedback import FeedbackStore, FeedbackError
            db = os.path.join(os.path.dirname(os.path.abspath(self.graph_path)),
                              "queries.db")
            if not os.path.exists(db):
                return _jf.dumps({"error": "无查询记录库"}, ensure_ascii=False)
            store = FeedbackStore(db)
            try:
                r = store.submit(
                    args["event_id"], args["relevance"],
                    task_outcome=args.get("outcome", "unknown"),
                    source="agent_relay", reason=args.get("reason"),
                    expected_evidence=args.get("expected"),
                    idempotency_key=args.get("idempotency_key"),
                    expected_revision=args.get("expected_revision"))
            except FeedbackError as e:
                return _jf.dumps({"error": str(e)}, ensure_ascii=False)
            finally:
                store.close()
            r = dict(r, source="agent_relay")  # 让调用方看见其判定以非权威来源落库
            return _jf.dumps(r, ensure_ascii=False)
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
            from .service import ServiceError
            try:
                r = self.svc.impact(args["symbol"], args.get("depth", 2), args.get("max_nodes", 200))
            except ServiceError as e:
                if e.code == "not_found":
                    return "无匹配符号"
                raise
            return _j.dumps({
                "start": ["[%s] %s @%s" % (n["kind"], n["name"], n["file"]) for n in r["start"]],
                "deps": ["%s --%s--> %s" % (a["name"], b, c["name"]) for a, b, c in r["deps"]],
                "total_deps": r["total"], "truncated": int(r["truncated"]),
                "partial": r["partial"]}, ensure_ascii=False)
        if name == "kg_doc_search":
            docs, r, obs = self.svc.doc_search(args["query"], "mcp")
            if not docs:
                return "文档无匹配（诚实拒答：不编造）。" + r["text"][:200]
            return "\n".join("- %s @%s" % (d["name"], d["file"]) for d in docs)
        if name == "kg_context":
            import json as _jc
            ctx = self.svc.trusted_context(scope=args.get("scope") or None)
            head = {"roots": [r["label"] for r in ctx["roots"]], "scope": ctx["scope"],
                    "items": [{"root": i["root"], "path": i["path"], "sha256": i["sha256"][:12],
                               "effective": bool(i.get("effective"))} for i in ctx["items"]],
                    "changed": ctx["changed"], "truncated": ctx["truncated"], "dropped": ctx["dropped"]}
            if ctx.get("note"):
                head["note"] = ctx["note"]
            out = _jc.dumps(head, ensure_ascii=False)
            if args.get("include_text", True) and ctx["text"]:
                out += "\n\n" + ctx["text"]
            return out
        if name == "kg_troubleshoot":
            from .scenario import scenario_trb
            return scenario_trb(self.g, self.s, args["symptom"])
        raise ValueError("unknown tool " + name)

def _request_lines(stream):
    """Yield bounded frames; None represents one oversized line, fully drained."""
    while True:
        line = stream.readline(MAX_REQUEST_CHARS + 1)
        if not line:
            return
        if len(line) > MAX_REQUEST_CHARS:
            while line and not line.endswith("\n"):
                line = stream.readline(MAX_REQUEST_CHARS + 1)
            yield None
        elif line.strip():
            yield line


def _error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def _response(srv, req):
    if not isinstance(req, dict):
        return _error(None, -32600, "invalid request")
    rid = req.get("id")
    valid_id = (rid is None or (isinstance(rid, str) and len(rid) <= 256) or type(rid) is int
                or (type(rid) is float and math.isfinite(rid)))
    if (req.get("jsonrpc") != "2.0" or not isinstance(req.get("method"), str) or not valid_id):
        return _error(rid if valid_id else None, -32600, "invalid request")
    # Write tools are gated in Server.call(); notifications never get a reply or a tool execution.
    if "id" not in req:
        return None
    params = req.get("params", {})
    if not isinstance(params, dict):
        return _error(rid, -32602, "invalid params")
    method = req["method"]
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "domimap", "version": __version__}}
    elif method == "tools/list":
        result = {"tools": visible_tools(srv.enable_write)}
    elif method == "tools/call":
        result = srv.call(params.get("name"), params.get("arguments", {}))
    elif method == "ping":
        result = {}
    else:
        return _error(rid, -32601, "method not found")
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _reject_constant(value):
    raise ValueError("non-JSON numeric constant")


def serve(graph_path, enable_write=False):
    srv = Server(graph_path, enable_write=enable_write)
    for line in _request_lines(sys.stdin):
        if line is None:
            response = _error(None, -32600, "request too large")
        else:
            try:
                req = json.loads(line, parse_constant=_reject_constant)
            except (ValueError, RecursionError):
                response = _error(None, -32700, "parse error")
            else:
                response = _response(srv, req)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
