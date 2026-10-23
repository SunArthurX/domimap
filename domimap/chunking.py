"""chunking — 索引层长文档分段（product-doc-chunking）。

动机：长文档（docx/长 md）单节点在 BM25 饱和长度归一下被稀释、嵌入只取前 2000 字符
（相关段落在后段）。分段只发生在索引层（Searcher 倒排与嵌入向量池），图文件零改动；
chunk 项 id=<nid>#cN，file/kind 与原文档一致（路径级命中与族归属不变）。
"""
CHUNK_THRESHOLD = 3500   # 超过此字符数的 Doc/长文才分段
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 250


def split_chunks(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """按换行边界切 ≤size 的段（重叠 overlap）；无换行长段硬切。返回段列表（≥1）。"""
    text = (text or "").strip()
    if len(text) <= size:
        return [text] if text else []
    lines, chunks, cur = text.split("\n"), [], []
    cur_len = 0
    for line in lines:
        add = len(line) + 1
        if cur and cur_len + add > size:
            chunks.append("\n".join(cur).strip())
            # 重叠：保留尾部若干行（累计 ≈ overlap）
            keep, keep_len = [], 0
            for prev in reversed(cur):
                if keep_len + len(prev) + 1 > overlap:
                    break
                keep.insert(0, prev)
                keep_len += len(prev) + 1
            cur, cur_len = keep, keep_len
        cur.append(line)
        cur_len += add
    tail = "\n".join(cur).strip()
    if tail:
        chunks.append(tail)
    # 无换行的超长单行硬切兜底
    out = []
    for c in chunks:
        while len(c) > size * 1.5:
            out.append(c[:size])
            c = c[size - overlap:]
        if c:
            out.append(c)
    return out


def node_text(node):
    """节点可分段的正文（Doc/Knowledge 全文；SqlStmt SQL）。"""
    kind = node.get("kind", "?")
    meta = node.get("meta") or {}
    if kind in ("Doc", "Knowledge"):
        return meta.get("text") or ""
    if kind == "SqlStmt":
        return meta.get("sql") or ""
    return ""


def expand_node(nid, node, threshold=CHUNK_THRESHOLD):
    """长文本文档 → [(chunk_id, chunk_node)]（浅拷贝改 name/meta.text；id/file/kind 原样语义）。
    短文档返回 [(nid, None)]（含义：无需分段，调用方直接用原节点）。"""
    text = node_text(node)
    if len(text) <= threshold:
        return [(nid, None)]
    chunks = split_chunks(text)
    if len(chunks) <= 1:
        return [(nid, None)]
    out = []
    for i, c in enumerate(chunks):
        cn = dict(node)
        cn["name"] = (node.get("name") or "")[:40] + " ·段%d" % (i + 1)
        cn["meta"] = dict(node.get("meta") or {})
        cn["meta"]["text" if node["kind"] in ("Doc", "Knowledge") else "sql"] = c
        cn["meta"]["chunk_of"] = nid
        out.append(("%s#c%d" % (nid, i + 1), cn))
    return out
