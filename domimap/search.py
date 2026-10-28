"""search — 混合检索：词法种子（IDF 加权）→ 1 跳图扩展 → token/字符预算内渲染。

graphify 的 trigram/IDF 思想 lite 版：不做 trigram 倒排（规模小），直接对节点文本建倒排。
"""
import json
import math
import os
import re
from collections import Counter, defaultdict

from .tokenize import tokenize

IDX_SCHEMA = "domimap.idx.v2"  # v2：索引层长文档分段（product-doc-chunking）

# 通用词集合：仅命中这些词不足以定位任何实质概念（负例拒答守门；不含真实业务域词，
# 防误拒面扩大——集合只放检索后缀/问法词，永不放订单/商品这类域词）
GENERIC_UNITS = {"规则", "配置", "定义", "说明", "位置", "处理", "服务", "管理",
                 "查询", "入口", "系统", "信息", "文档", "地址", "内容", "支持"}
# 名称精确匹配加权：查询标识符与节点 name 完全相等（定义性同一）×3——干净集实测
# tbl 节点仅凭 op_operator 得 0.53 分被通用词堆叠的 DTO（1.29）压出 top50。
# 限定（retrieval-identifier-boost-scope）：只对原始查询的标识符生效——seeds 域扩展
# 词与类名撞名（商品→Item）不构成用户表达的"定义性同一"，曾把含原实词的文档压到
# top_k 外（真实语料 rank 15 实证）。
IDENTIFIER_NAME_BOOST = 3.0
# seeds 域扩展词的计分权重（retrieval-identifier-boost-scope 候选 2）：原始查询词是
# 用户表达的证据；扩展词只是词法桥（召回通道）。同权竞争曾让扩展英文词凭内容堆分
# 把含原始中文实词的文档压出 top_k（真实语料 rank 15/12 双目标实证）。0.35≈1/3：
# 3 个扩展命中 ≈ 1 个原始词命中；覆盖率门/拒答判定不受此权重影响。
EXPANSION_TOKEN_WEIGHT = 0.35
BM25_K = 1.2
BM25_B = 0.75
DECAY_FLOOR = 0.05
# 文档类型先验：文件名含这些关键词的文档在文档路加 ×1.5（公共语料评测实证：
# 中文查询"接入 教程"匹配不上英文 README 标题词——类型先验补偿词汇鸿沟的非桥部分）
DOC_TYPE_PRIOR = 1.0  # 禁用：公共语料实测 README 宽泛内容被推过特定 gold 致 doc/fresh 回退
DDL_SEMANTIC_BOOST = 2.0  # DDL 语义匹配：查询含"表/定义/写入"时 CREATE TABLE 的 SqlStmt ×2
SEM_COV_GATE = 0.6        # 语义桥触发门：覆盖率低于此且查询含 CJK 才触发（跨语言信号）
_DOC_TYPE_HINTS = ("readme", "tutorial", "getting started", "quickstart",
                   "changelog", "spec", "guide", "manual", "migration")

class Searcher:
    def __init__(self, g, cache_path=None, coverage=None):
        self.g = g
        self.coverage = coverage or {}
        self.docs = {}
        self.df = Counter()
        self.N = 0
        self._dl_sum = 0
        self.avgdl = 1.0
        self.extra = {}  # 人工知识等非机器图节点（R05：重建不丢，查询时挂载）
        self.cjk4 = set()  # 正文里真实出现过的连续四字，用来判断长词是不是整段存在
        self._cjk4_ready = False
        if cache_path and self._load_idxdb(cache_path):
            pass
        elif cache_path and self._load_cache(cache_path):
            pass
        else:
            self._build()
            if cache_path and getattr(g, "sig", None):
                self._persist_idxdb(cache_path)
        # 语义桥磁盘缓存（可选层；未启用不读不写）
        self._bridge_cache = (cache_path + ".bridge.json") if cache_path else None
        if self._bridge_cache:
            from .semantic_bridge import load_disk_cache
            load_disk_cache(self._bridge_cache)
        # LLM 重排磁盘缓存（可选层）
        self._rerank_cache = (cache_path + ".rerank.json") if cache_path else None
        if self._rerank_cache:
            from .llm_rerank import load_disk_cache as _lr_load
            _lr_load(self._rerank_cache)
        # 嵌入索引 sidecar（可选层；cache_path 通常为 <graph>.idx.json → 图旁 .emb.json）
        self.emb_store = None
        self.emb_backend_factory = None
        if cache_path:
            gp = cache_path[:-len(".idx.json")] if cache_path.endswith(".idx.json") else None
            if gp:
                from .embedding import load_store, store_path_for
                self.emb_store = load_store(store_path_for(gp))

    def _note_cjk4(self, text):
        for run in re.findall(r"[\u4e00-\u9fff]{4,}", text or ""):
            self.cjk4.update(run[i:i + 4] for i in range(len(run) - 3))

    def _ensure_cjk4(self):
        if self._cjk4_ready:
            return
        self.cjk4 = set()
        for n in self.g.nodes.values():
            self._note_cjk4(self._node_text(n))
        for n in self.extra.values():
            self._note_cjk4(self._node_text(n))
        self._cjk4_ready = True

    def _phrase_absent(self, text, matched):
        """整段不在、只靠散落二字加上通用词命中时才拒答。

        「价格同步监听」这类查询的二字本身就是检索词，不在这里拒。
        「量子纠缠玄学术语毫无关系」没有任何二字命中，留给覆盖率门。
        「冷链温控巡检 规则 配置」：长词的二字散落在别处，剩下的只有规则/配置。
        """
        runs = re.findall(r"[\u4e00-\u9fff]{6,}", text or "")
        if not runs or not matched:
            return False
        self._ensure_cjk4()
        unsupported = []
        for run in runs:
            if all(run[i:i + 4] in self.cjk4 for i in range(len(run) - 3)):
                return False
            unsupported.append(run)
        noise = set()
        for run in unsupported:
            noise.update(run[i:i + 2] for i in range(len(run) - 1))
        if not (matched & noise):
            return False
        rest = matched - noise
        return (not rest) or rest <= GENERIC_UNITS

    def _ident_in_graph(self, ident):
        low = ident.lower()
        if any(low in token for token in self.df):
            return True
        nodes = list(self.g.nodes.values()) + list(self.extra.values())
        return any(low in (n.get("name") or "").lower() for n in nodes)

    def _node(self, nid):
        return self.g.nodes.get(nid) or self.extra[nid]

    def attach_knowledge(self, kb, current_digests=None):
        """把 KnowledgeStore 的 active 笔记挂进检索索引（kind=Knowledge，Doc 路参与）。

        current_digests 提供时，依据已变且未绑定当前版本的 claim 标 stale（F4-02）。
        """
        flagged = kb.claims_with_flags(current_digests) if current_digests is not None else None
        from .knowledge import LLM_NOTE_PREFIX
        for note in kb.list_active():
            nid = "kn:" + note["note_id"]
            claims = flagged[note["note_id"]] if flagged else note["claims"]
            llm_origin = note["body"].startswith(LLM_NOTE_PREFIX)
            self.extra[nid] = {"id": nid, "kind": "Knowledge",
                               "name": note["body"][:48], "file": "knowledge:" + note["note_id"],
                               "meta": {"text": note["body"], "claims": claims},
                               "conf": "LLM" if llm_origin else "HUMAN",
                               "prov": "knowledge:llm" if llm_origin else "knowledge"}
            self._index_one(nid)
            self._note_cjk4(note["body"])

    def _index_one(self, nid):
        n = self.extra[nid]
        tks = tokenize(self._node_text(n))
        self.docs[nid] = Counter(tks)
        for t in set(tks):
            self.index[t].add(nid)
            self.df[t] = len(self.index[t])
        self.N += 1
        self._dl_sum += sum(self.docs[nid].values())
        self.avgdl = max(1.0, self._dl_sum / self.N)

    def _sig_ok(self, d):
        sig = getattr(self.g, "sig", None)
        return bool(sig and d.get("schema") == IDX_SCHEMA
                    and d.get("graph_mtime") == sig["mtime"] and d.get("graph_size") == sig["size"]
                    and d.get("node_count") == len(self.g.nodes))

    def _restore_chunk_nodes(self):
        from .chunking import expand_node
        for nid, n in self.g.nodes.items():
            if n.get("kind") in ("Doc", "Knowledge", "SqlStmt"):
                for cid, cn in expand_node(nid, n):
                    if cn is not None:
                        self.extra[cid] = cn

    def _idxdb_file(self, cache_path):
        from .idxdb import idxdb_path
        return idxdb_path(cache_path)

    def _load_idxdb(self, cache_path):
        """命中 SQLite 倒排时不把 posting 装进内存。图指纹不一致则当未命中。"""
        from .idxdb import IdxDB, LazyDocs, LazyIndex
        path = self._idxdb_file(cache_path)
        if not os.path.exists(path):
            return False
        store = IdxDB(path)
        if not store.matches(getattr(self.g, "sig", None), len(self.g.nodes)):
            store.close()
            return False
        self._idxdb = store
        self.df = Counter(store.vocabulary())
        self.N, self.avgdl = store.stats()
        self._dl_sum = self.avgdl * max(1, self.N)
        self.docs = LazyDocs(store)
        self.index = LazyIndex(store)
        self._restore_chunk_nodes()
        return True

    def _persist_idxdb(self, cache_path):
        from .idxdb import write_idx_db
        write_idx_db(self._idxdb_file(cache_path), self.docs, self.index, self.N, self.avgdl,
                     self.g.sig, len(self.g.nodes))
        self._load_idxdb(cache_path)

    def _load_cache(self, path):
        """命中条件：schema 版本一致 + 图文件 mtime/size/节点数指纹一致（否则重建）。"""
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return False
        if not self._sig_ok(d):
            return False
        self.docs = {nid: Counter(dict(pairs)) for nid, pairs in d["docs"].items()}
        self.index = defaultdict(set, {t: set(ids) for t, ids in d["index"].items()})
        self.df = Counter({t: len(v) for t, v in self.index.items()})
        self.N = d["N"]
        self._dl_sum = sum(sum(c.values()) for c in self.docs.values())
        self.avgdl = max(1.0, self._dl_sum / max(1, self.N))
        self._restore_chunk_nodes()
        return True

    def _save_cache(self, path):
        sig = self.g.sig
        d = {"schema": IDX_SCHEMA, "graph_mtime": sig["mtime"], "graph_size": sig["size"],
             "node_count": len(self.g.nodes), "N": self.N,
             "docs": {nid: [[t, c] for t, c in cnt.items()] for nid, cnt in self.docs.items()},
             "index": {t: sorted(ids) for t, ids in self.index.items()}}
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, path)

    def _node_text(self, n):
        parts = [n["name"], n["kind"], n["file"]]
        if n["kind"] == "Doc":
            parts.append(n["meta"].get("text", "")[:50000])
        if n["kind"] == "SqlStmt":
            parts.append(n["meta"].get("sql", ""))
        if n["kind"] in ("Table", "Column"):
            parts.append(n["meta"].get("comment", ""))
            cc = n["meta"].get("col_comments") or {}
            if isinstance(cc, dict):
                parts.append(" ".join(str(v) for v in cc.values()))
        if n["kind"] == "Class":
            # 类注释关键词：业务中文查询与代码节点之间的词面桥（第 5 步诊断驱动）
            parts.append(n["meta"].get("comment", ""))
        if n["kind"] == "Knowledge":
            # 笔记全文 + claim 陈述入索引：name 只是 body 前 48 字符（LLM 溯源前缀
            # 更长时中文全被截断——真实 GLM e2e 发现中文摘要完全不可检索的根因）。
            parts.append(n["meta"].get("text", "")[:20000])
            parts.append(" ".join(str(c.get("statement", "")) for c in n["meta"].get("claims", [])))
        return " \n ".join(parts)

    def _build(self):
        self.index = defaultdict(set)
        self._dl_sum = 0
        for nid, n in self.g.nodes.items():
            tks = tokenize(self._node_text(n))
            self.docs[nid] = Counter(tks)
            for t in set(tks):
                self.index[t].add(nid)
            self.N += 1
            self._dl_sum += sum(self.docs[nid].values())
        # 索引层长文档分段（product-doc-chunking）：chunk 注册进 extra（_node 回退 extra，
        # 渲染/路径/file 语义不变）；同文件 ≤2 席的防霸榜语义顺带限流单文件 chunk 数
        from .chunking import expand_node
        for nid, n in list(self.g.nodes.items()):
            if n.get("kind") not in ("Doc", "Knowledge", "SqlStmt"):
                continue
            for cid, cn in expand_node(nid, n):
                if cn is None:
                    continue
                self.extra[cid] = cn
                tks = tokenize(self._node_text(cn))
                self.docs[cid] = Counter(tks)
                for t in set(tks):
                    self.index[t].add(cid)
                self.N += 1
                self._dl_sum += sum(self.docs[cid].values())
        self.avgdl = max(1.0, self._dl_sum / max(1, self.N))
        self.df = Counter({t: len(s) for t, s in self.index.items()})

    def _score(self, qtokens, nid, name_tokens=None, weak_tokens=None):
        d = self.docs.get(nid, Counter())
        if not d:
            return 0.0
        dl = sum(d.values()) or 1
        # BM25 饱和长度归一（k=1.2/b=0.75）：线性 tf/total 曾使短注释节点（dl≈20）
        # 对任意共享词碾压 50KB 文档（1/20000）——doc/fresh 查询全被挤出的根因
        norm = 1.0 - BM25_B + BM25_B * (dl / self.avgdl)
        s = 0.0
        for qt in qtokens:
            if len(qt) == 1 and ord(qt) > 0x2E7F:
                continue  # 单字 CJK 是子词级噪声：曾让通用尾词凭计数压过精确标识符命中
            tf = d.get(qt)
            if tf:
                idf = math.log(1 + (self.N - self.df.get(qt, 0) + 0.5)
                               / (self.df.get(qt, 0) + 0.5))
                weight = (EXPANSION_TOKEN_WEIGHT
                          if weak_tokens and qt in weak_tokens else 1.0)
                s += weight * idf * tf * (BM25_K + 1) / (tf + BM25_K * norm)
        return s * (IDENTIFIER_NAME_BOOST
                    if self._name_exact_hit(name_tokens if name_tokens is not None
                                            else qtokens, nid) else 1.0) \
            * (DOC_TYPE_PRIOR if self._doc_type_hint(nid) else 1.0) \
            * (DDL_SEMANTIC_BOOST if self._ddl_semantic_hit(qtokens, nid) else 1.0)

    def _ddl_semantic_hit(self, qtokens, nid):
        """DDL 语义匹配：DDL 来源的 Table/SqlStmt 节点 + 查询含表/定义/写入词。
        公共语料实测：DDL 文件的 BM25 分数被含长注释的 Java 引用压出 top5（2 题）。"""
        n = self._node(nid)
        if n["kind"] == "Table":
            if n.get("prov") != "sql:ddl":
                return False
        elif n["kind"] == "SqlStmt":
            if "CREATE TABLE" not in n["meta"].get("sql", "").upper():
                return False
        else:
            return False
        qset = set(qtokens)
        return bool(qset & {"表", "定义", "写入", "位置", "ddl", "建表", "create"})

    def _doc_type_hint(self, nid):
        """文件名含 README/Tutorial/Guide/CHANGELOG/SPEC 等提示词的文档路加先验。"""
        n = self._node(nid)
        if n["kind"] not in ("Doc", "Knowledge"):
            return False
        fname = n["file"].lower()
        return any(h in fname for h in _DOC_TYPE_HINTS)

    def _name_exact_hit(self, qtokens, nid):
        """查询拉丁标识符与节点 name 完全相等（定义性同一）：仅精确相等，不猜相近名。"""
        n = self._node(nid)
        name = n["name"].lower()
        if len(name) < 4:
            return False
        for qt in qtokens:
            if len(qt) >= 4 and qt == name:
                return True
        return False

    @staticmethod
    def _units(text):
        """查询单元：latin 词（小写，含 camelCase/snakeCase 切分，与 tokenize 词表对齐）
        + CJK 连续段二元组（段长 1 时取单字）。"""
        import re as _re
        out = set()
        for m in _re.finditer(r"[A-Za-z][A-Za-z0-9_]*", text):
            w = m.group(0)
            out.add(w.lower())
            parts = _re.findall(r"[a-z]+|[A-Z][a-z]*", w)
            if len(parts) > 1:
                out.update(p.lower() for p in parts if len(p) > 1)
        for m in _re.finditer(r"[\u4e00-\u9fff\u3040-\u30ff]+", text):
            seg = m.group(0)
            if len(seg) == 1:
                out.add(seg)
            else:
                out.update(seg[i:i+2] for i in range(len(seg) - 1))
        return out

    def load_embeddings(self, path):
        """显式加载嵌入索引 sidecar（基准回放/无 cache_path 场景）。失败保持 None。"""
        from .embedding import load_store
        store = load_store(path)
        if store:
            self.emb_store = store
        return self.emb_store

    def set_embedding_backend(self, factory):
        """注入查询期嵌入后端工厂（测试/自定义后端；None=默认 local/api 按环境）。"""
        self.emb_backend_factory = factory

    def _score_matched(self, matched, qt, qt_orig, weak_tokens, cov, domain, as_of):
        """词法候选打分。返回 (候选 id 集, 按分排序的 (score, nid))。"""
        cand = set()
        for t in matched:
            cand |= self.index.get(t, set())
        import time as _t
        clock = as_of if as_of is not None else _t.time()
        scored = []
        for nid in cand:
            if not self._keep_candidate(nid, domain, as_of, clock):
                continue
            s = self._score(qt, nid, name_tokens=qt_orig, weak_tokens=weak_tokens) * cov * cov
            if s > 0:
                scored.append((s, nid))
        scored.sort(reverse=True)
        return cand, scored

    def _refusal_for_gap(self, cov, scored, strong, min_cov, domain):
        """覆盖率、空候选、无强信号三种拒答。条件都不成立时返回 None。"""
        if not (cov < min_cov or not scored or not strong):
            return None
        if cov < min_cov:
            text = ("（诚实拒答：查询词覆盖率 %.0f%%，不足 %d%% 阈值。已查 %d 节点；"
                    "建议换关键词/先 build。）" % (cov * 100, min_cov * 100, self.N))
            reason = "coverage_below_min"
        elif not scored:
            if domain:
                text = ("（诚实拒答：覆盖率 %.0f%% 达标，但域过滤「%s」后无候选。已查 %d 节点；"
                        "检查领域值（领域地图可查可用域）或去掉域过滤。）"
                        % (cov * 100, domain, self.N))
                reason = "domain_filter_empty"
            else:
                text = ("（诚实拒答：覆盖率 %.0f%% 达标，但无强命中候选。已查 %d 节点；"
                        "建议换关键词/先 build。）" % (cov * 100, self.N))
                reason = "no_strong_candidate"
        else:
            text = ("（诚实拒答：查询无实质词强信号（仅通用词不构成依据），不猜。已查 %d 节点。）"
                    % (self.N,))
            reason = "no_strong_candidate"
        return {"seeds": [], "expanded": [], "text": text, "refused": True,
                "refusal_reason": reason, "cov": round(cov, 4), "min_cov": min_cov}

    def _keep_candidate(self, nid, domain, as_of, clock):
        """资格先于排序：被替代、已过期、晚于 as_of 的节点不进候选。非法日期不猜。"""
        n = self._node(nid)
        if domain and n["meta"].get("domain") != domain:
            return False
        m = n["meta"]
        if m.get("superseded_by"):
            return False
        vu = m.get("valid_until")
        if vu:
            import calendar
            import time as _t
            try:
                if calendar.timegm(_t.strptime(vu[:10], "%Y-%m-%d")) < clock:
                    return False
            except ValueError:
                pass
        if as_of is not None and m.get("first_seen", 0) > as_of:
            return False
        return True

    def _lane_of(self, nid):
        kind = self._node(nid)["kind"]
        if kind == "Knowledge":
            return "kn"
        return "doc" if kind == "Doc" else "code"

    def _lane_prepare(self, pairs):
        """路内：同文件 ≤2 席，再按路内最高分的 45% 截尾。"""
        fam, kept = {}, []
        for s, nid in sorted(pairs, reverse=True):
            f = self._node(nid)["file"]
            fam[f] = fam.get(f, 0) + 1
            if fam[f] <= 2:
                kept.append((s, nid))
        if len(kept) >= 2:
            top = kept[0][0]
            kept = [kept[0]] + [x for x in kept[1:] if x[0] >= 0.45 * top]
        return kept

    def _select_hits(self, scored, top_k, query_text, rerank, rerank_pool):
        """三路保底融合，可选 LLM 重排。返回 (merged, rerank_info)。"""
        lanes = {"code": [], "doc": [], "kn": []}
        for s, nid in scored:
            lanes[self._lane_of(nid)].append((s, nid))
        lanes = {k: self._lane_prepare(v) for k, v in lanes.items() if v}
        guaranteed, taken = [], set()
        for lane, cap in (("code", 2), ("doc", 2), ("kn", 1)):
            for item in lanes.get(lane, [])[:cap]:
                guaranteed.append(item)
                taken.add(item[1])
        rest = sorted((x for lane in lanes.values() for x in lane if x[1] not in taken),
                      reverse=True)
        merged = sorted(guaranteed + rest, reverse=True)[:top_k]
        gua_ids = {nid for _, nid in guaranteed}
        in_final = {nid for _, nid in merged}
        for gsc, gnid in guaranteed:
            if gnid in in_final:
                continue
            for j in range(len(merged) - 1, -1, -1):
                if merged[j][1] not in gua_ids:
                    merged[j] = (gsc, gnid)
                    in_final.add(gnid)
                    break
        merged.sort(reverse=True)
        pool = sorted((x for lane in lanes.values() for x in lane), reverse=True)[:max(20, top_k)]
        sel_fams = {self._node(nid)["file"].split("/", 1)[0] for _, nid in merged}
        for sc, nid in pool:
            fseg = self._node(nid)["file"].split("/", 1)[0]
            if fseg in sel_fams:
                continue
            if (len(merged) >= top_k and sc > merged[-1][0]
                    and merged[-1][1] not in gua_ids):
                merged[-1] = (sc, nid)
            elif len(merged) < top_k:
                merged.append((sc, nid))
            else:
                break
            sel_fams.add(fseg)
            merged.sort(reverse=True)
        rerank_info = None
        from . import llm_rerank as _lr
        if _lr.enabled(rerank):
            flat = sorted((x for lane in lanes.values() for x in lane), reverse=True)
            if len(flat) > top_k:
                pool_n = min(int(rerank_pool or _lr.DEFAULT_POOL), _lr.MAX_POOL, len(flat))
                rr_pool = flat[:pool_n]
                ordered, rr_note = _lr.rerank(query_text, rr_pool, self._node,
                                              cache_path=self._rerank_cache)
                if ordered:
                    pool_map = {nid: (sc, nid) for sc, nid in rr_pool}
                    seq = [pool_map[n] for n in ordered][:top_k]
                    seq_lanes = {self._lane_of(nid) for _, nid in seq}
                    for lane in lanes:
                        if lane in seq_lanes:
                            continue
                        first = next((pool_map[n] for n in ordered
                                      if self._lane_of(n) == lane), None)
                        if first is None:
                            continue
                        from collections import Counter as _Cnt
                        cnt = _Cnt(self._lane_of(nid) for _, nid in seq)
                        victim = max(cnt, key=cnt.get) if cnt else None
                        for j in range(len(seq) - 1, -1, -1):
                            if victim is None or self._lane_of(seq[j][1]) == victim:
                                seq[j] = first
                                break
                    merged = seq
                    rerank_info = {"pool": len(rr_pool), "note": rr_note}
        return merged, rerank_info

    def _apply_semantic_bridge(self, enabled_flag, original, orig_units, graph_has_cjk,
                               is_cjk, cand, scored, cov, strong, qset, qt_orig,
                               weak_tokens, denom, min_cov, domain, as_of):
        """可选语义桥。默认关闭时原样返回。日期资格沿用桥内的本地时区换算。"""
        sem_info, sem_units = None, set()
        from . import semantic_bridge as _sb
        if not _sb.enabled(enabled_flag):
            return sem_info, sem_units, cand, scored, cov, strong
        orig_denom = {u for u in orig_units if not is_cjk(u)} | \
                     ({u for u in orig_units if is_cjk(u)} if graph_has_cjk else set())
        orig_matched = {t for t in orig_denom if t in self.df}
        orig_cov = (len(orig_matched) / len(orig_denom)) if orig_denom else 0.0
        if not (orig_cov < SEM_COV_GATE and any(is_cjk(u) for u in orig_units)):
            return sem_info, sem_units, cand, scored, cov, strong
        sem_tokens, sem_note = _sb.expand_tokens(original, self.df, cache_path=self._bridge_cache)
        grounded = [t for t in sem_tokens if t in self.df]
        if not grounded:
            return sem_info, sem_units, cand, scored, cov, strong
        sem_units = set(grounded)
        sem_info = {"tokens": grounded, "note": sem_note}
        for t in sem_units:
            cand |= self.index.get(t, set())

        def eligible(nid):
            n = self._node(nid)
            if domain and n["meta"].get("domain") != domain:
                return False
            if as_of is not None:
                m = n["meta"]
                if m.get("superseded_by"):
                    return False
                vu = m.get("valid_until")
                if vu:
                    import time as _t
                    try:
                        if _t.mktime(_t.strptime(vu[:10], "%Y-%m-%d")) < as_of:
                            return False
                    except ValueError:
                        pass
                if m.get("first_seen", 0) > as_of:
                    return False
            return True

        denom_sem = denom | sem_units
        matched_sem = {t for t in denom_sem if t in self.df}
        if cov < min_cov:
            cov = (len(matched_sem) / len(denom_sem)) if denom_sem else 0
            strong = strong or bool(matched_sem)
        scored = []
        for nid in cand:
            if not eligible(nid):
                continue
            s_sem = self._score(list(qset | sem_units), nid, name_tokens=qt_orig,
                                weak_tokens=weak_tokens) * cov * cov
            if s_sem > 0:
                scored.append((s_sem, nid))
        scored.sort(reverse=True)
        return sem_info, sem_units, cand, scored, cov, strong

    def _apply_en_bridge(self, units, denom, cand, scored, cov, strong, qset, sem_units, qt_orig):
        """覆盖率不足时，用内置中英词表补一次候选。主路径不计这些词。"""
        from .tokenize import EN_BRIDGE
        ext_tokens = set()
        for u in units:
            ens = EN_BRIDGE.get(u)
            if ens:
                ext_tokens.update(ens if not isinstance(ens, str) else [ens])
        if not ext_tokens:
            return cand, scored, cov, strong
        ext_matched = {t for t in ext_tokens if t in self.df}
        if not ext_matched:
            return cand, scored, cov, strong
        for t in ext_matched:
            cand |= self.index.get(t, set())
        cov = len(ext_matched) / len(ext_tokens | denom) if (ext_tokens | denom) else 0
        scored = []
        for nid in cand:
            s2_ = self._score(list(qset | ext_matched | sem_units), nid,
                              name_tokens=qt_orig) * cov * cov
            if s2_ > 0:
                scored.append((s2_, nid))
        scored.sort(reverse=True)
        return cand, scored, cov, True

    def _fuse_embeddings(self, scored, qset, qt, original, embed):
        """可选嵌入融合。定义性标识符或代码意图词跳过，避免稀释词法精确命中。"""
        from . import embedding as _eb
        embed_info = None
        if not (_eb.enabled(embed) and self.emb_store):
            return scored, embed_info
        code_intent = qset & {"表", "定义", "写入", "位置", "ddl", "建表", "create",
                              "处理类", "列名", "字段", "哪个类", "哪个服务", "读写"}
        has_definitive = any(self._name_exact_hit(qt, nid) for _, nid in scored[:10])
        if has_definitive or code_intent:
            return scored, {"backend": self.emb_store.get("backend"),
                            "skipped": "definitive_identifier" if has_definitive else "code_intent"}
        sem_pairs = _eb.semantic_recall(
            original, self.emb_store, backend_factory=self.emb_backend_factory,
            kinds=("Doc", "Knowledge"))
        if sem_pairs:
            fused = _eb.fuse_rrf(scored, sem_pairs)
            if fused:
                return fused, {"backend": self.emb_store.get("backend"), "sem_top": len(sem_pairs)}
        return scored, embed_info

    def _reweight_fresh(self, scored, text):
        """查询带时间词时，按 first_seen 在当前候选里做有界近因加权。只改排序。"""
        import re
        if not re.search(r"最新|最近|更新|变更|changelog|change", text, re.I):
            return scored
        fss = [self._node(nid)["meta"].get("first_seen") or 0.0 for _, nid in scored[:200]]
        mx = max(fss) if fss else 0.0
        mn = min(fss) if fss else 0.0
        if mx <= mn:
            return scored
        return [(s * (0.5 + 0.5 * ((self._node(nid)["meta"].get("first_seen") or 0.0) - mn)
                      / (mx - mn)), nid) for s, nid in scored]

    def _assemble_result(self, merged, top_k, expand, budget, as_of, sem_info, rerank_info, embed_info):
        """渲染种子、一跳扩展和覆盖缺口。"""
        now_ref = as_of if as_of is not None else __import__("time").time()

        def time_note(nid):
            fs = self._node(nid)["meta"].get("first_seen")
            if not fs:
                return "日期未知：不衰减（按最早资格处理）"
            age_days = max(0.0, (now_ref - fs) / 86400.0)
            decay = 0.5 ** (age_days / 365.0)
            return "age=%.0fd decay=%.3f" % (age_days, decay)

        hits = merged[:top_k]
        seed_ids = [nid for _, nid in hits]
        seen = set(seed_ids)
        lines = ["## 种子命中（词法 IDF）"]
        for idx, (s, nid) in enumerate(hits):
            node = self._node(nid)
            node["time_note"] = time_note(nid)
            lines.append(self._render(node, s, rank=idx + 1))
        exp_lines = []
        if expand:
            lines.append("\n## 一跳扩展（图结构）")
            for nid in seed_ids:
                for e in self.g.neighbors(nid) + self.g.neighbors(nid, rev=True)[:4]:
                    other = self.g.nodes.get(e["dst"] if e["src"] == nid else e["src"])
                    if not other or other["id"] in seen:
                        continue
                    seen.add(other["id"])
                    exp_lines.append("- %s --%s(%s)--> %s" % (
                        self.g.nodes[nid]["name"], e["kind"], e["conf"], other["name"]))
        out = "\n".join(lines + exp_lines)
        if sem_info:
            out = "（语义桥扩展：%s）\n%s" % (" ".join(sem_info["tokens"]), out)
        if len(out) > budget:
            out = out[:budget] + "\n…(预算截断)"
        reasons = {}
        for skipped in (self.coverage.get("skipped") or []):
            for key in ("解析失败", "旧格式", "大小上限", "越界", "lambda", "未解析"):
                if key in skipped.get("reason", ""):
                    reasons[key] = reasons.get(key, 0) + 1
        return {"seeds": [self._node(n) for n in seed_ids], "expanded_count": len(exp_lines),
                "text": out, "refused": False,
                "semantic_bridge": sem_info, "llm_rerank": rerank_info, "embedding": embed_info,
                "coverage": {"files_scanned": self.coverage.get("files_scanned"),
                             "skipped": len(self.coverage.get("skipped") or []), "reasons": reasons}}

    def query(self, text, top_k=6, expand=True, budget=3800, domain=None, min_cov=0.3, seeds=None,
              as_of=None, semantic=None, rerank=None, rerank_pool=None, embed=None):
        """as_of（epoch 秒）给定时时先做资格筛选：first_seen 晚于 as_of 的节点不进候选（F4）。

        标识符守门（先于词表扩展）：单一 latin 标识符且图中无任何节点名/索引词包含它时
        直接拒答——不猜相近名（防变异标识符的幻觉命中，负例底线）。
        """
        import re as _reG
        _o = text.strip()
        if (_reG.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", _o)
                and not self._ident_in_graph(_o)):
            return {"seeds": [], "expanded": [],
                    "text": "（诚实拒答：标识符 %s 在图中不存在。）" % _o, "refused": True,
                    "refusal_reason": "identifier_absent"}
        """seeds（领域种子词表）提供时启用查询期领域扩展：命中域的关键词拼入检索，
        解决纯中文查询与 latin 词面节点的词法鸿沟（与 scenario_req 同一公共语义）。"""
        weak_tokens = set()
        if seeds:
            from .scenario import classify
            doms = [d for d in classify(text, seeds)]
            ext = []
            for d in doms:
                ext.extend(seeds[d].get("keywords", [])[:6])
                ext.extend(seeds[d].get("prefixes", [])[:4])
            for cn, en in (seeds.get("_synonyms") or {}).items():
                if cn in text:
                    ext.extend(en)   # 中英词法桥：域无关查询同义词
            if ext:
                text = text + " " + " ".join(ext)
                # 扩展词降权集：仅扩展拼入、原始查询未出现的 token（原始词全权）
                weak_tokens = set(tokenize(text)) - set(tokenize(_o))
        # 原始查询单元（先于 seeds 域扩展计算）：语义桥触发门用——seeds 拼入的英文域词
        # 会把覆盖率抬高，掩盖中文查询与英文内容之间的真实词法鸿沟（pub A/B 实测发现）
        orig_units = self._units(_o)
        qt_orig = tokenize(_o)  # 名称精确加成的合法标识符来源（不含扩展词）
        qt = tokenize(text)
        qset = set(qt)
        if not qset:
            return {"seeds": [], "expanded": [], "text": "空查询。", "refused": True,
                    "refusal_reason": "empty_query"}
        # 词覆盖率门（graphify #1602 思想）+ 语言感知：按"查询单元"计（latin 词 + CJK 二元组），
        # 纯代码仓无中文语料时中文单元不计分母；命中需至少一个强单元（≥2 字符）。
        units = self._units(text)
        if not units:
            return {"seeds": [], "expanded": [], "text": "空查询。", "refused": True,
                    "refusal_reason": "empty_query"}
        graph_has_cjk = any(any(ord(c) > 0x2E7F for c in t) for t in self.df)
        def is_cjk(t):
            return any(ord(c) > 0x2E7F for c in t)
        denom = {u for u in units if not is_cjk(u)} | \
                ({u for u in units if is_cjk(u)} if graph_has_cjk else set())
        matched = {t for t in denom if t in self.df}
        cov = (len(matched) / len(denom)) if denom else 0.0
        # 负例守门①：命中的单元全部是通用问法词 → 查询的全部实质概念在图中不存在，
        # 拒答（诊断实证："对账差异自动核销 规则 配置"曾因 规则/配置 命中返回假阳性）
        if matched and matched <= GENERIC_UNITS:
            return {"seeds": [], "expanded": [],
                    "text": "（诚实拒答：查询的实质词在图中均不存在，仅命中通用词。）",
                    "refused": True, "refusal_reason": "generic_only",
                    "cov": round(cov, 4), "min_cov": min_cov}
        if self._phrase_absent(_o, matched):
            return {"seeds": [], "expanded": [],
                    "text": "（诚实拒答：查询里的长词在图中没有整段出现，不拿散落的二字凑答案。）",
                    "refused": True, "refusal_reason": "phrase_absent",
                    "cov": round(cov, 4), "min_cov": min_cov}
        # 负例守门②：含 ≥4 字符拉丁标识符且全部缺席 → 拒答（原守门仅覆盖纯标识符查询，
        # "近名标识符+中文词"曾绕过并产生幻觉命中）。名字检查覆盖全部节点，不再截断前 20 万。
        import re as _reI
        _idents = _reI.findall(r"[A-Za-z][A-Za-z0-9_]{3,}", _o)
        _all_absent = all(not self._ident_in_graph(i) for i in _idents)
        if _idents and _all_absent:
            return {"seeds": [], "expanded": [],
                    "text": "（诚实拒答：标识符 %s 在图中不存在。）" % ", ".join(_idents[:3]),
                    "refused": True, "refusal_reason": "identifier_absent",
                    "cov": round(cov, 4), "min_cov": min_cov}
        cand, scored = self._score_matched(matched, qt, qt_orig, weak_tokens, cov, domain, as_of)
        strong = any(len(t) >= 2 and t in self.df for t in denom)
        sem_info, sem_units, cand, scored, cov, strong = self._apply_semantic_bridge(
            semantic, _o, orig_units, graph_has_cjk, is_cjk, cand, scored, cov, strong,
            qset, qt_orig, weak_tokens, denom, min_cov, domain, as_of)
        if cov < min_cov or not scored or not strong:
            cand, scored, cov, strong = self._apply_en_bridge(
                units, denom, cand, scored, cov, strong, qset, sem_units, qt_orig)
            gap = self._refusal_for_gap(cov, scored, strong, min_cov, domain)
            if gap:
                return gap
        scored, embed_info = self._fuse_embeddings(scored, qset, qt, _o, embed)
        scored = self._reweight_fresh(scored, text)
        scored.sort(reverse=True)
        merged, rerank_info = self._select_hits(scored, top_k, _o, rerank, rerank_pool)
        return self._assemble_result(merged, top_k, expand, budget, as_of,
                                    sem_info, rerank_info, embed_info)

    def _render(self, n, score, rank=None):
        head = "- [%s] %s  (score=%.3f, conf=%s, prov=%s)" % (n["kind"], n["name"], score, n["conf"], n["prov"])
        if rank is not None:
            head += " [rank:#%d]" % rank
        if n["kind"] == "SqlStmt":
            sql = n["meta"].get("sql", "")
            head += " [DDL]" if "CREATE TABLE" in sql.upper() else ""
            head += "\n    SQL: " + sql[:160]
        if n["kind"] == "Table" and n.get("prov") == "sql:ddl":
            head += " [DDL]"
        if n["kind"] in ("Doc", "Knowledge"):
            head += " [type:%s]" % self._infer_doc_type(n["file"])
        if n["kind"] == "Knowledge":
            stale = [c for c in n["meta"].get("claims", []) if c.get("stale")]
            if stale:  # 依据已变且未确认绑定：检索面如实标注（R06-02 / F4-02）
                head += " [stale:%d 条陈述待复核]" % len(stale)
        if n["meta"].get("domain"):
            head += "  [域:%s%s]" % (n["meta"]["domain"], "/vote" if n["meta"].get("domain_by") else "")
        if n.get("time_note"):  # 时效可解释（F4）：纪元来源 + 衰减说明；有效期如实展示
            head += "  [time:%s%s]" % (n["time_note"],
                                      (" era=" + n["meta"]["era_source"]) if n["meta"].get("era_source") else "")
        if n["meta"].get("valid_until"):
            head += "  [valid_until:%s]" % n["meta"]["valid_until"]
        return head + "\n    @" + n["file"]

    @staticmethod
    def _infer_doc_type(fname):
        """文件名推断文档类型（仅信息标注，不影响排序——第 1 轮先验加成教训）。"""
        low = fname.lower()
        if "readme" in low:
            return "README"
        if "changelog" in low or "change_log" in low or "changes" in low:
            return "CHANGELOG"
        if "spec" in low:
            return "SPEC"
        if any(w in low for w in ("tutorial", "getting", "quickstart", "demo")):
            return "TUTORIAL"
        if "guide" in low or "manual" in low:
            return "GUIDE"
        if "migrat" in low or "upgrade" in low:
            return "MIGRATION"
        return "DOC"
