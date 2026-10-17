"""search — 混合检索：词法种子（IDF 加权）→ 1 跳图扩展 → token/字符预算内渲染。

graphify 的 trigram/IDF 思想 lite 版：不做 trigram 倒排（规模小），直接对节点文本建倒排。
"""
import json
import math
import os
from collections import Counter, defaultdict

from .tokenize import tokenize

IDX_SCHEMA = "domimap.idx.v1"

class Searcher:
    def __init__(self, g, cache_path=None, coverage=None):
        self.g = g
        self.coverage = coverage or {}
        self.docs = {}
        self.df = Counter()
        self.N = 0
        self.extra = {}  # 人工知识等非机器图节点（R05：重建不丢，查询时挂载）
        if cache_path and self._load_cache(cache_path):
            pass
        else:
            self._build()
            if cache_path and getattr(g, "sig", None):
                self._save_cache(cache_path)

    def _node(self, nid):
        return self.g.nodes.get(nid) or self.extra[nid]

    def attach_knowledge(self, kb, current_digests=None):
        """把 KnowledgeStore 的 active 笔记挂进检索索引（kind=Knowledge，Doc 路参与）。

        current_digests 提供时，依据已变且未绑定当前版本的 claim 标 stale（F4-02）。
        """
        flagged = kb.claims_with_flags(current_digests) if current_digests is not None else None
        for note in kb.list_active():
            nid = "kn:" + note["note_id"]
            claims = flagged[note["note_id"]] if flagged else note["claims"]
            self.extra[nid] = {"id": nid, "kind": "Knowledge",
                               "name": note["body"][:48], "file": "knowledge:" + note["note_id"],
                               "meta": {"text": note["body"], "claims": claims},
                               "conf": "HUMAN", "prov": "knowledge"}
            self._index_one(nid)

    def _index_one(self, nid):
        n = self.extra[nid]
        tks = tokenize(self._node_text(n))
        self.docs[nid] = Counter(tks)
        for t in set(tks):
            self.index[t].add(nid)
        self.df[t] = len(self.index[t]) if False else self.df  # df 惰性重算见下
        for t in set(tks):
            self.df[t] = len(self.index[t])
        self.N += 1

    def _sig_ok(self, d):
        sig = getattr(self.g, "sig", None)
        return bool(sig and d.get("schema") == IDX_SCHEMA
                    and d.get("graph_mtime") == sig["mtime"] and d.get("graph_size") == sig["size"]
                    and d.get("node_count") == len(self.g.nodes))

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
        if n["kind"] == "Class":
            # 类注释关键词：业务中文查询与代码节点之间的词面桥（第 5 步诊断驱动）
            parts.append(n["meta"].get("comment", ""))
        return " \n ".join(parts)

    def _build(self):
        self.index = defaultdict(set)
        for nid, n in self.g.nodes.items():
            tks = tokenize(self._node_text(n))
            self.docs[nid] = Counter(tks)
            for t in set(tks):
                self.index[t].add(nid)
            self.N += 1
        self.df = Counter({t: len(s) for t, s in self.index.items()})

    def _score(self, qtokens, nid):
        d = self.docs.get(nid, Counter())
        if not d:
            return 0.0
        total = sum(d.values()) or 1
        s = 0.0
        for qt in qtokens:
            if qt in d:
                idf = math.log(1 + self.N / (1 + self.df.get(qt, 0)))
                s += idf * (d[qt] / total)
        return s

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

    def query(self, text, top_k=6, expand=True, budget=3800, domain=None, min_cov=0.3, seeds=None,
              as_of=None):
        """as_of（epoch 秒）给定时时先做资格筛选：first_seen 晚于 as_of 的节点不进候选（F4）。

        标识符守门（先于词表扩展）：单一 latin 标识符且图中无任何节点名/索引词包含它时
        直接拒答——不猜相近名（防变异标识符的幻觉命中，负例底线）。
        """
        import re as _reG
        _o = text.strip()
        if (_reG.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", _o)
                and not any(_o.lower() in n["name"].lower()
                            for n in list(self.g.nodes.values())[:200000] + list(self.extra.values()))
                and not any(_o.lower() in t for t in self.df)):
            return {"seeds": [], "expanded": [],
                    "text": "（诚实拒答：标识符 %s 在图中不存在。）" % _o, "refused": True}
        """seeds（领域种子词表）提供时启用查询期领域扩展：命中域的关键词拼入检索，
        解决纯中文查询与 latin 词面节点的词法鸿沟（与 scenario_req 同一公共语义）。"""
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
        qt = tokenize(text)
        qset = set(qt)
        if not qset:
            return {"seeds": [], "expanded": [], "text": "空查询。", "refused": True}
        # 词覆盖率门（graphify #1602 思想）+ 语言感知：按"查询单元"计（latin 词 + CJK 二元组），
        # 纯代码仓无中文语料时中文单元不计分母；命中需至少一个强单元（≥2 字符）。
        units = self._units(text)
        if not units:
            return {"seeds": [], "expanded": [], "text": "空查询。", "refused": True}
        graph_has_cjk = any(any(ord(c) > 0x2E7F for c in t) for t in self.df)
        def is_cjk(t):
            return any(ord(c) > 0x2E7F for c in t)
        denom = {u for u in units if not is_cjk(u)} | \
                ({u for u in units if is_cjk(u)} if graph_has_cjk else set())
        matched = {t for t in denom if t in self.df}
        cov = (len(matched) / len(denom)) if denom else 0.0
        cand = set()
        for t in matched:
            cand |= self.index.get(t, set())
        scored = []
        for nid in cand:
            n = self._node(nid)
            if domain and n["meta"].get("domain") != domain:
                continue
            if as_of is not None:
                m = n["meta"]
                if m.get("superseded_by"):
                    continue  # 已被替代：默认排除（历史查询经显式参数，M3 复核接入）
                vu = m.get("valid_until")
                if vu:
                    import calendar, time as _t
                    try:
                        if _t.mktime(_t.strptime(vu[:10], "%Y-%m-%d")) < as_of:
                            continue  # 过期资料不具资格
                    except ValueError:
                        pass  # 日期非法：不猜，保持资格并记未知
                if m.get("first_seen", 0) > as_of:
                    continue  # 晚于 as_of 的资料不参与
            s = self._score(qt, nid) * cov * cov
            if s > 0:
                scored.append((s, nid))
        scored.sort(reverse=True)
        strong = any(len(t) >= 2 and t in self.df for t in denom)
        if cov < min_cov or not scored or not strong:
            return {"seeds": [], "expanded": [],
                    "text": "（诚实拒答：查询词覆盖率 %.0f%%，不足 %d%% 阈值。已查 %d 节点；建议换关键词/先 build。）" % (cov * 100, min_cov * 100, self.N),
                    "refused": True}
        # 时新意图：查询含时间词时按 first_seen 近因加权（文件 mtime 为资格事实）
        import re as _re0
        fresh_query = bool(_re0.search(r"最新|最近|更新|变更|changelog|change", text, _re0.I))
        if fresh_query:
            fss = [self._node(nid)["meta"].get("first_seen") or 0.0 for _, nid in scored[:200]]
            mx = max(fss) if fss else 0.0
            mn = min(fss) if fss else 0.0
            if mx > mn:
                scored = [(s * (0.5 + 0.5 * ((self._node(nid)["meta"].get("first_seen") or 0.0) - mn)
                                / (mx - mn)), nid) for s, nid in scored]
        # 时间衰减：仅作用于排序（资格已筛完），逐条 explain（F4）
        now_ref = as_of if as_of is not None else __import__("time").time()

        def time_note(nid):
            fs = self._node(nid)["meta"].get("first_seen")
            if not fs:
                return "日期未知：不衰减（按最早资格处理）"
            age_days = max(0.0, (now_ref - fs) / 86400.0)
            decay = 0.5 ** (age_days / 365.0)
            return "age=%.0fd decay=%.3f" % (age_days, decay)

        scored = [(s * (0.5 ** (max(0.0, (now_ref - (self._node(nid)["meta"].get("first_seen") or now_ref)) / 86400.0) / 365.0)), nid)
                  for s, nid in scored]
        scored.sort(reverse=True)
        # R04-01：①来源家族去重（同文件 ≤2 席，防 seeds/README 型噪声霸榜）②分路融合（Doc 保底）
        fam, capped = {}, []
        for s, nid in scored:
            f = self._node(nid)["file"]
            fam[f] = fam.get(f, 0) + 1
            if fam[f] <= 2:
                capped.append((s, nid))
        # 跨族覆盖：top_k 选择后，若得分前 20 的其它族无代表，则用该族最佳替换选择尾部最低分项
        # （全局最佳始终保留；替换按族头得分与被替项得分顺序进行——不破坏排序质量）
        sel = capped[:top_k]
        pool = capped[:max(20, top_k)]
        sel_fams = {self._node(nid)["file"].split("/", 1)[0] for _, nid in sel}
        for sc, nid in pool:
            fseg = self._node(nid)["file"].split("/", 1)[0]
            if fseg in sel_fams:
                continue
            if len(sel) >= top_k and sc > sel[-1][0]:
                sel[-1] = (sc, nid)          # 替换最低分尾部
            elif len(sel) < top_k:
                sel.append((sc, nid))
            else:
                break
            sel_fams.add(fseg)
            sel.sort(reverse=True)
        capped = sel + capped[top_k:]
        doc_hits = [x for x in capped if self._node(x[1])["kind"] in ("Doc", "Knowledge")]
        code_hits = [x for x in capped if self._node(x[1])["kind"] not in ("Doc", "Knowledge")]
        # 文档路配额自适应：候选头部文档浓度高（文档型查询）时扩到 3 席，防代码挤占
        head = capped[:10]
        doc_dense = len(doc_hits) >= 3 and sum(1 for _, nid in head
                                               if self._node(nid)["kind"] in ("Doc", "Knowledge")) >= 4
        want_docs = min(3 if doc_dense else 2, len(doc_hits)) if doc_hits else 0
        merged = (code_hits[:top_k - want_docs] + doc_hits[:want_docs]) if want_docs else capped[:top_k]
        # 候选精剪（precision）：与上一名得分断崖 >55% 时截断（丢弃低置信尾部，减 FP）
        if len(merged) >= 2:
            keep = [merged[0]]
            for i in range(1, len(merged)):
                if merged[i][0] >= 0.45 * merged[0][0]:
                    keep.append(merged[i])
            merged = keep
        seeds = merged[:top_k]
        seed_ids = [nid for _, nid in seeds]
        seen = set(seed_ids)
        lines = ["## 种子命中（词法 IDF）"]
        for s, nid in seeds:
            node = self._node(nid)
            node["time_note"] = time_note(nid)
            lines.append(self._render(node, s))
        exp_lines = []
        if expand:
            lines.append("\n## 一跳扩展（图结构）")
            for nid in seed_ids:
                for e in self.g.neighbors(nid) + self.g.neighbors(nid, rev=True)[:4]:
                    other = self.g.nodes.get(e["dst"] if e["src"] == nid else e["src"])
                    if not other or other["id"] in seen:
                        continue
                    seen.add(other["id"])
                    exp_lines.append("- %s --%s(%s)--> %s" % (self.g.nodes[nid]["name"], e["kind"], e["conf"], other["name"]))
        out = "\n".join(lines + exp_lines)
        if len(out) > budget:
            out = out[:budget] + "\n…(预算截断)"
        reasons = {}
        for s in (self.coverage.get("skipped") or []):
            for key in ("解析失败", "旧格式", "大小上限", "越界", "lambda", "未解析"):
                if key in s.get("reason", ""):
                    reasons[key] = reasons.get(key, 0) + 1
        return {"seeds": [self._node(n) for n in seed_ids], "expanded_count": len(exp_lines),
                "text": out, "refused": False,
                "coverage": {"files_scanned": self.coverage.get("files_scanned"),
                             "skipped": len(self.coverage.get("skipped") or []), "reasons": reasons}}

    def _render(self, n, score):
        head = "- [%s] %s  (score=%.3f, conf=%s, prov=%s)" % (n["kind"], n["name"], score, n["conf"], n["prov"])
        if n["kind"] == "SqlStmt":
            head += "\n    SQL: " + n["meta"].get("sql", "")[:160]
        if n["meta"].get("domain"):
            head += "  [域:%s%s]" % (n["meta"]["domain"], "/vote" if n["meta"].get("domain_by") else "")
        return head + "\n    @" + n["file"]
