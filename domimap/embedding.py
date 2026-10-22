"""embedding — 可选嵌入索引：语义召回经 RRF 融合并入检索（product-embedding-index）。

动机（三重证据链终局）：59/74 的 pub 图内 miss 中 gold 在 BM25 原始序 >200 名 40 个、
无词面交集 19 个——词法桥/查询扩展/LLM 重排全部零效果，只有嵌入索引可达全名次。
嵌入目标 = Doc + Knowledge + SqlStmt + Table（59 人口的 gold 构成 .sql 41 + .md 39 + .docx 1；
pub 图实测 ~2750 节点）。

后端（flag > env > 默认）：
- local（默认，主用）：fastembed + BAAI/bge-small-zh-v1.5（512 维，离线免费，开源友好）；
  可选依赖——import 失败时清晰报错（LlmConfigError 同型），核心与 hermetic 测试零依赖。
  bge 标准用法：查询侧加检索指令前缀，文档侧不加。
- api：bigmodel /api/paas/v4/embeddings（embedding-3）。**2026-10-22 实测 1113"余额不足
  或无可用资源包"——已实现但当前不可用**；`DOMIMAP_EMBED_BACKEND=api` 启用。

纪律（对齐 enrich/bridge/rerank，R05/R08）：
- 默认关：DOMIMAP_EMBED=1 或 query --embed；拒答守门先于融合（负例结构性安全）。
- 建索引幂等：键 = nid + 文本 sha，未变不重算；图旁 <graph>.emb.json（向量 5 位小数）。
- 失败降级：索引缺失/后端缺失/向量损坏 → BM25 原序，绝不空结果、绝不拒答变化。
- 融合：RRF（K=60，参数无关标准法）——score = Σ 1/(60+rank)，融合后的序与分值替换
  scored 进入后续流程（时新/重排/三路融合逻辑零变化）。
"""
import hashlib
import json
import os
import time

EMB_ENV = "DOMIMAP_EMBED"
BACKEND_ENV = "DOMIMAP_EMBED_BACKEND"
EMB_SCHEMA = "domimap.emb.v1"
LOCAL_MODEL = "BAAI/bge-small-zh-v1.5"
BGE_QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
MAX_TEXT_CHARS = 2000        # 文档侧截断（Doc 全文过长；BM25 索引用 50000，嵌入用短文足够）
MAX_SQL_CHARS = 400
RRF_K = 60
TOPN = 500                   # BM25/语义两序各取前 500 融合

_QUERY_CACHE = {}            # sha(query) -> vec（进程内）
_BACKEND_SINGLETON = None    # (name, backend)——本地模型加载重，进程内复用


class EmbeddingUnavailable(RuntimeError):
    """后端不可用（依赖缺失/配置错）——调用方优雅回退 BM25 序。"""


def enabled(explicit=None):
    if explicit is not None:
        return bool(explicit)
    return os.environ.get(EMB_ENV, "").strip() in ("1", "true", "yes", "on")


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class LocalFastembedBackend:
    name = "local:" + LOCAL_MODEL

    def __init__(self):
        try:
            from fastembed import TextEmbedding
        except ImportError as error:
            raise EmbeddingUnavailable(
                "本地嵌入后端需要 fastembed（pip install fastembed）：%s" % error)
        self._model = TextEmbedding(LOCAL_MODEL)

    def embed_texts(self, texts):
        return [list(v) for v in self._model.embed(texts)]

    def embed_query(self, text):
        return list(next(iter(self._model.embed([BGE_QUERY_PREFIX + text]))))


class ApiBackend:
    """bigmodel embeddings（2026-10-22 余额阻塞，实现保留）。"""

    name = "api:embedding-3"

    def __init__(self, api_key=None, endpoint=None, model="embedding-3", dims=512):
        from .llm_enrich import load_api_key
        self.api_key = api_key or load_api_key()
        self.endpoint = endpoint or os.environ.get("DOMIMAP_EMBED_ENDPOINT") \
            or "https://open.bigmodel.cn/api/paas/v4/embeddings"
        self.model = os.environ.get("DOMIMAP_EMBED_MODEL") or model
        self.dims = int(os.environ.get("DOMIMAP_EMBED_DIMS") or dims)

    def _post(self, texts):
        import urllib.request
        payload = {"model": self.model, "input": texts, "dimensions": self.dims}
        req = urllib.request.Request(
            self.endpoint, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.api_key})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                out = json.loads(resp.read())
        except Exception as error:
            raise EmbeddingUnavailable("嵌入 API 失败：%s" % str(error)[:160])
        data = out.get("data") or []
        return [d["embedding"] for d in sorted(data, key=lambda d: d.get("index", 0))]

    def embed_texts(self, texts):
        out = []
        for i in range(0, len(texts), 16):   # 批量上限保守 16
            out.extend(self._post(texts[i:i + 16]))
            if i + 16 < len(texts):
                time.sleep(0.2)
        return out

    def embed_query(self, text):
        return self._post([text])[0]


def make_backend(name=None):
    """按名称构造后端（进程内单例——本地模型加载 ~10s，绝不每查询重建）。"""
    global _BACKEND_SINGLETON
    name = name or os.environ.get(BACKEND_ENV) or "local"
    if _BACKEND_SINGLETON and _BACKEND_SINGLETON[0] == name:
        return _BACKEND_SINGLETON[1]
    backend = ApiBackend() if name == "api" else LocalFastembedBackend()
    _BACKEND_SINGLETON = (name, backend)
    return backend


def node_text(node):
    """嵌入文本：名称/类型/路径 + 截断正文（SQL 语句 / 文档正文）。"""
    kind = node.get("kind", "?")
    parts = [node.get("name") or "", kind, node.get("file") or ""]
    meta = node.get("meta") or {}
    if kind in ("Doc", "Knowledge"):
        parts.append((meta.get("text") or "")[:MAX_TEXT_CHARS])
    elif kind == "SqlStmt":
        parts.append((meta.get("sql") or "")[:MAX_SQL_CHARS])
    elif kind == "Table":
        parts.append((meta.get("ddl") or meta.get("sql") or "")[:MAX_SQL_CHARS])
    return " \n ".join(p for p in parts if p)


EMBED_KINDS = {"docs": ("Doc", "Knowledge"), "sql": ("SqlStmt", "Table"),
               "all": ("Doc", "Knowledge", "SqlStmt", "Table")}


def build_index(graph, targets="all", backend_factory=None, limit=None, existing=None):
    """幂等建库：返回 (store dict, 统计)。键 = nid；sha 未变项复用既有向量（零重算）。"""
    backend = (backend_factory or make_backend)()
    kinds = EMBED_KINDS.get(targets)
    if kinds is None:
        raise ValueError("targets 取值 docs|sql|all，收到 %r" % targets)
    old_items = (existing or {}).get("items") or {}
    items = {}
    for nid, node in graph.nodes.items():
        if node.get("kind") not in kinds:
            continue
        text = node_text(node)
        if not text.strip():
            continue
        sha = _sha(text)
        prev = old_items.get(nid)
        if prev and prev.get("sha") == sha and prev.get("vec"):
            items[nid] = {"sha": sha, "vec": prev["vec"]}
        else:
            items[nid] = {"sha": sha}
    if limit:
        nids = sorted(items)[:limit]
        items = {k: items[k] for k in nids}
    stats = {"total": len(items),
             "embedded": sum(1 for v in items.values() if "vec" not in v),
             "reused": sum(1 for v in items.values() if "vec" in v),
             "backend": backend.name}
    todo = [n for n, v in items.items() if "vec" not in v]
    if todo:
        vecs = backend.embed_texts([node_text(graph.nodes[n]) for n in todo])
        for nid, vec in zip(todo, vecs):
            items[nid]["vec"] = [round(float(x), 5) for x in vec]
    store = {"schema": EMB_SCHEMA, "backend": backend.name,
             "dims": len(next(iter(items.values()))["vec"]) if items else 0,
             "built_at": time.time(), "items": items}
    return store, stats


def store_path_for(graph_path):
    return graph_path + ".emb.json"


def save_store(store, path):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False)
    os.replace(tmp, path)


def load_store(path):
    try:
        with open(path, encoding="utf-8") as f:
            store = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(store, dict) or store.get("schema") != EMB_SCHEMA:
        return None
    return store if isinstance(store.get("items"), dict) and store["items"] else None


def _cosine_top(query_vec, items, top_n=TOPN):
    """查询向量 → 语义序 [(cos, nid)]。numpy 可用时矩阵化（42k×512 纯 Python 过慢）。"""
    try:
        import numpy as _np
        ids = list(items)
        mat = _np.array([items[n]["vec"] for n in ids], dtype=_np.float32)
        q = _np.array(query_vec, dtype=_np.float32)
        denom = (_np.linalg.norm(mat, axis=1) * _np.linalg.norm(q))
        denom[denom == 0] = 1e-9
        sims = (mat @ q) / denom
        idx = _np.argsort(-sims)[:top_n]
        return [(float(sims[i]), ids[i]) for i in idx]
    except ImportError:
        import math
        qn = math.sqrt(sum(x * x for x in query_vec)) or 1e-9
        scored = []
        for nid, it in items.items():
            v = it["vec"]
            dot = sum(a * b for a, b in zip(v, query_vec))
            nv = math.sqrt(sum(a * a for a in v)) or 1e-9
            scored.append((dot / (nv * qn), nid))
        scored.sort(reverse=True)
        return scored[:top_n]


def fuse_rrf(bm25_pairs, sem_pairs, k=RRF_K):
    """RRF 融合两序 → 新 [(rrf_score, nid)] 序（分数即可比融合分，进入下游流程）。"""
    scores = {}
    for rank, (_, nid) in enumerate(bm25_pairs[:TOPN]):
        scores[nid] = scores.get(nid, 0.0) + 1.0 / (k + rank + 1)
    for rank, (_, nid) in enumerate(sem_pairs[:TOPN]):
        scores[nid] = scores.get(nid, 0.0) + 1.0 / (k + rank + 1)
    fused = sorted(((s, n) for n, s in scores.items()), reverse=True)
    return fused


def semantic_recall(query_text, store, backend_factory=None):
    """查询 → 语义序 [(cos, nid)]；任何失败/维度不匹配返回 None（调用方回退 BM25 序）。"""
    key = _sha(query_text)
    cached = _QUERY_CACHE.get(key)
    try:
        if cached is None:
            backend = (backend_factory or make_backend)()
            cached = backend.embed_query(query_text)
            if len(_QUERY_CACHE) >= 128:
                _QUERY_CACHE.clear()
            _QUERY_CACHE[key] = cached
        if store.get("dims") and len(cached) != store["dims"]:
            return None  # 后端/索引维度不匹配：不猜，回退词法序
        return _cosine_top(cached, store["items"])
    except EmbeddingUnavailable:
        return None
    except Exception:
        return None
