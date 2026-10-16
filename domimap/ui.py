"""ui — 本地只读搜索与证据阅读页面（F2：无模型可用；仅回环监听）。

与 CLI/MCP 共用同一 Searcher+seeds 语义（AC-F2-01 三入口同源同序）。
stdlib http.server 实现，无第三方依赖；拒绝非回环绑定。
"""
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from .graph import Graph, load_seeds
from .search import Searcher

PAGE = """<!doctype html><html lang="zh"><meta charset="utf-8">
<title>domimap 搜索</title>
<body style="font-family:system-ui;max-width:880px;margin:2rem auto">
<h3>domimap 本地搜索（只读）</h3>
<form onsubmit="return go()">
<input id="q" style="width:60%%;padding:.4rem" placeholder="自然语言 / 符号名（支持中文）">
<input id="d" style="width:14%%;padding:.4rem" placeholder="领域(可选)">
<button>搜索</button></form>
<div id="r" style="margin-top:1rem;white-space:pre-wrap"></div>
<script>
async function go(){
  const q=document.getElementById('q').value;
  const d=document.getElementById('d').value;
  const r=await (await fetch('/api/search?q='+encodeURIComponent(q)+(d?'&domain='+encodeURIComponent(d):''))).json();
  document.getElementById('r').textContent =
    r.refused ? '（诚实拒答）'+(r.text||'') :
    r.seeds.map(s=>`- [${s.kind}] ${s.name}  @${s.file}`).join('\\n');
  return false;
}
</script></body></html>"""


def make_server(graph_path, host="127.0.0.1", port=0):
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("本地 UI 仅允许回环绑定（安全边界 R08）")
    g = Graph.load(graph_path)
    searcher = Searcher(g, cache_path=graph_path + ".idx.json")
    seeds = load_seeds(os.path.join(os.path.dirname(os.path.abspath(__file__)), "seeds.json"))

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # 安静模式
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        _LOOPBACK = ("http://127.0.0.1", "http://localhost", "http://[::1]")

        def _origin_ok(self):
            """R08-02：Host 必须回环；Origin/Referer 若存在必须回环（跨站写拒绝）。"""
            host = (self.headers.get("Host") or "").split(":")[0]
            if host not in ("127.0.0.1", "localhost", "[::1]", "::1"):
                return False
            for h in ("Origin", "Referer"):
                v = self.headers.get(h)
                if v and not any(v.startswith(p) for p in self._LOOPBACK):
                    return False
            return True

        def do_POST(self):
            if self.path == "/api/note/save":
                if not self._origin_ok():
                    n = int(self.headers.get("Content-Length") or 0)
                    if n:
                        self.rfile.read(min(n, 1 << 20))  # 排空请求体再应答，保证连接语义
                    self._send(403, json.dumps({"error": "跨站/非回环来源写入被拒绝"}, ensure_ascii=False))
                    return
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(min(n, 1 << 20)).decode("utf-8"))
                except Exception:
                    self._send(400, json.dumps({"error": "非法请求体"}, ensure_ascii=False))
                    return
                from .knowledge import KnowledgeStore
                kb_path = os.path.join(os.path.dirname(os.path.abspath(graph_path)), "knowledge.db")
                kb = KnowledgeStore(kb_path)
                try:
                    r = kb.submit(body.get("body", ""), body.get("claims") or [],
                                  idempotency_key=body.get("idempotency_key"))
                except ValueError as e:
                    self._send(409, json.dumps({"error": str(e)}, ensure_ascii=False))
                    return
                finally:
                    kb.close()
                self._send(200, json.dumps(r, ensure_ascii=False))
                return
            self._send(404, json.dumps({"error": "not found"}))

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/":
                self._send(200, PAGE, "text/html; charset=utf-8")
                return
            if u.path == "/api/search":
                q = (parse_qs(u.query).get("q") or [""])[0]
                dom = (parse_qs(u.query).get("domain") or [None])[0]
                if not q.strip():
                    self._send(400, json.dumps({"error": "空查询"}, ensure_ascii=False))
                    return
                r = searcher.query(unquote(q), top_k=6, expand=False, domain=dom, seeds=seeds)
                self._send(200, json.dumps(
                    {"seeds": [{"id": n["id"], "kind": n["kind"], "name": n["name"],
                                "file": n["file"]} for n in r["seeds"]],
                     "refused": r.get("refused", False), "text": r["text"][:400],
                     "coverage": r.get("coverage")},
                    ensure_ascii=False))
                return
            if u.path == "/api/read":
                ev = (parse_qs(u.query).get("ev") or [""])[0]
                if not re.fullmatch(r"ev:[0-9a-f]{4,40}", ev):
                    self._send(400, json.dumps({"error": "非法证据 ID"}, ensure_ascii=False))
                    return
                from .store import EvidenceStore
                db = os.path.join(os.path.dirname(os.path.abspath(graph_path)), "store.db")
                if not os.path.exists(db):
                    self._send(404, json.dumps({"available": False, "reason": "无证据库"}))
                    return
                store = EvidenceStore(db)
                row = store.db.execute("SELECT sid FROM evidence WHERE ev_id=?", (ev,)).fetchone()
                if not row:
                    store.close()
                    self._send(404, json.dumps({"available": False, "reason": "证据 ID 不存在"}))
                    return
                out = store.evidence_for_source(row[0])
                store.close()
                self._send(200, json.dumps({k: (v[:4000] if k == "text" else v)
                                            for k, v in out.items()}, ensure_ascii=False))
                return
            self._send(404, json.dumps({"error": "not found"}))

    return ThreadingHTTPServer((host, port), H)


def serve_forever(graph_path, host, port):
    srv = make_server(graph_path, host, port)
    print("domimap ui: http://%s:%d （仅回环，Ctrl-C 退出）" % (host, srv.server_address[1]))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
