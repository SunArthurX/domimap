"""图健康基线：节点/边计数、每方法 CALLS 均值、重复边比例。大图走流式计数，不整文件 json.load。"""
import json
import os
import re
import sys

_KIND = re.compile(r'"kind"\s*:\s*"([A-Za-z_]+)"')


def summarize_obj(doc):
    nodes = doc.get("nodes") or []
    edges = doc.get("edges") or []
    node_kinds = {}
    methods = 0
    for n in nodes:
        k = n.get("kind")
        node_kinds[k] = node_kinds.get(k, 0) + 1
        if k == "Method":
            methods += 1
    edge_kinds = {}
    seen = set()
    dup = 0
    calls = 0
    for e in edges:
        k = e.get("kind")
        edge_kinds[k] = edge_kinds.get(k, 0) + 1
        if k == "CALLS":
            calls += 1
        key = (e.get("src"), e.get("dst"), k)
        if key in seen:
            dup += 1
        else:
            seen.add(key)
    return {
        "nodes": len(nodes),
        "edges": len(edges),
        "node_kinds": node_kinds,
        "edge_kinds": edge_kinds,
        "calls": calls,
        "methods": methods,
        "calls_per_method": (calls / methods) if methods else 0.0,
        "duplicate_edges": dup,
        "mode": "json",
    }


def summarize_stream(path):
    """不解析完整 JSON：按 "kind" 字段计数。重复边在流式模式下不计算（duplicate_edges=null）。"""
    node_kinds, edge_kinds = {}, {}
    # 文件结构是 {"nodes":[...],"edges":[...]}。用花括号深度区分节点与边不可靠（meta 嵌套）。
    # 约定：先出现的 kind 计数归 nodes，直到读到 "edges" 键。
    in_edges = False
    methods = calls = 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        buf = ""
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            buf += chunk
            if not in_edges and '"edges"' in buf:
                head, buf = buf.split('"edges"', 1)
                for m in _KIND.finditer(head):
                    k = m.group(1)
                    node_kinds[k] = node_kinds.get(k, 0) + 1
                    if k == "Method":
                        methods += 1
                in_edges = True
            if in_edges and len(buf) > 200:
                body, buf = buf[:-100], buf[-100:]
                for m in _KIND.finditer(body):
                    k = m.group(1)
                    edge_kinds[k] = edge_kinds.get(k, 0) + 1
                    if k == "CALLS":
                        calls += 1
        text = buf
        bucket = edge_kinds if in_edges else node_kinds
        for m in _KIND.finditer(text):
            k = m.group(1)
            bucket[k] = bucket.get(k, 0) + 1
            if not in_edges and k == "Method":
                methods += 1
            if in_edges and k == "CALLS":
                calls += 1
    nodes = sum(node_kinds.values())
    edges = sum(edge_kinds.values())
    return {
        "nodes": nodes,
        "edges": edges,
        "node_kinds": node_kinds,
        "edge_kinds": edge_kinds,
        "calls": calls,
        "methods": methods,
        "calls_per_method": (calls / methods) if methods else 0.0,
        "duplicate_edges": None,
        "mode": "stream",
    }


def summarize(path, stream_after=256 * 1024 * 1024):
    if os.path.getsize(path) > stream_after:
        rec = summarize_stream(path)
    else:
        with open(path, encoding="utf-8") as f:
            rec = summarize_obj(json.load(f))
    rec["path"] = path
    rec["bytes"] = os.path.getsize(path)
    return rec


def main(argv):
    if len(argv) < 2:
        print("usage: graph_health.py <graph.json> [out.json]", file=sys.stderr)
        return 2
    rec = summarize(argv[1])
    text = json.dumps(rec, ensure_ascii=False, indent=1)
    if len(argv) >= 3:
        os.makedirs(os.path.dirname(os.path.abspath(argv[2])), exist_ok=True)
        with open(argv[2], "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
