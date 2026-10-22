"""search — 混合检索：词法种子（IDF 加权）→ 1 跳图扩展 → token/字符预算内渲染。

graphify 的 trigram/IDF 思想 lite 版：不做 trigram 倒排（规模小），直接对节点文本建倒排。
"""
import json
import math
import os
from collections import Counter, defaultdict

from .tokenize import tokenize

IDX_SCHEMA = "domimap.idx.v1"

# 通用词集合：仅命中这些词不足以定位任何实质概念（负例拒答守门；不含真实业务域词，
# 防误拒面扩大——集合只放检索后缀/问法词，永不放订单/商品这类域词）
GENERIC_UNITS = {"规则", "配置", "定义", "说明", "位置", "处理", "服务", "管理",
                 "查询", "入口", "系统", "信息", "文档", "地址", "内容", "支持"}
# 名称精确匹配加权：查询标识符与节点 name 完全相等（定义性同一）×3——干净集实测
# tbl 节点仅凭 op_operator 得 0.53 分被通用词堆叠的 DTO（1.29）压出 top50
IDENTIFIER_NAME_BOOST = 3.0
BM25_K = 1.2
BM25_B = 0.75
DECAY_FLOOR = 0.05
# 文档类型先验：文件名含这些关键词的文档在文档路加 ×1.5（公共语料评测实证：
# 中文查询"接入 教程"匹配不上英文 README 标题词——类型先验补偿词汇鸿沟的非桥部分）
DOC_TYPE_PRIOR = 1.0  # 禁用：公共语料实测 README 宽泛内容被推过特定 gold 致 doc/fresh 回退
DDL_SEMANTIC_BOOST = 2.0  # DDL 语义匹配：查询含"表/定义/写入"时 CREATE TABLE 的 SqlStmt ×2
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
        self.avgdl = max(1.0, self._dl_sum / max(1, self.N))
        self.df = Counter({t: len(s) for t, s in self.index.items()})

    def _score(self, qtokens, nid):
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
                s += idf * tf * (BM25_K + 1) / (tf + BM25_K * norm)
        return s * (IDENTIFIER_NAME_BOOST if self._name_exact_hit(qtokens, nid) else 1.0) \
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
        # 负例守门①：命中的单元全部是通用问法词 → 查询的全部实质概念在图中不存在，
        # 拒答（诊断实证："对账差异自动核销 规则 配置"曾因 规则/配置 命中返回假阳性）
        if matched and matched <= GENERIC_UNITS:
            return {"seeds": [], "expanded": [],
                    "text": "（诚实拒答：查询的实质词在图中均不存在，仅命中通用词。）",
                    "refused": True}
        # 负例守门②：含 ≥4 字符拉丁标识符且全部缺席 → 拒答（原守门仅覆盖纯标识符查询，
        # "近名标识符+中文词"曾绕过并产生幻觉命中）
        import re as _reI
        _idents = _reI.findall(r"[A-Za-z][A-Za-z0-9_]{3,}", _o)
        _all_absent = all(
            not any(i.lower() in n["name"].lower()
                    for n in list(self.g.nodes.values())[:200000] + list(self.extra.values()))
            and not any(i.lower() in t for t in self.df)
            for i in _idents)
        if _idents and _all_absent:
            return {"seeds": [], "expanded": [],
                    "text": "（诚实拒答：标识符 %s 在图中不存在。）" % ", ".join(_idents[:3]),
                    "refused": True}
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
            # 中英桥回退：原始查询覆盖率不足时，附加 CJK 二元组的英文对应词重试
            # （主路径不加桥——公共语料实测桥接加入主计分路径稀释 BM25 IDF 使 11 题回退）
            from .tokenize import EN_BRIDGE
            ext_tokens = set()
            for u in units:
                ens = EN_BRIDGE.get(u)
                if ens:
                    if isinstance(ens, str):
                        ext_tokens.add(ens)
                    else:
                        ext_tokens.update(ens)
            if ext_tokens:
                ext_matched = {t for t in ext_tokens if t in self.df}
                if ext_matched:
                    for t in ext_matched:
                        cand |= self.index.get(t, set())
                    cov = len(ext_matched) / len(ext_tokens | denom) if (ext_tokens | denom) else 0
                    scored = []
                    for nid in cand:
                        s2_ = self._score(list(qset | ext_matched), nid) * cov * cov
                        if s2_ > 0:
                            scored.append((s2_, nid))
                    scored.sort(reverse=True)
                    strong = True
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

        # 时效查询的时间乘子=有界近因重加权（第 5 轮终版）：独立指数衰减分支已移除——
        # 它对"如实声明日期"的节点系统性惩罚（未知时间 or now_ref → ×1.0 不衰减，
        # 声明 2017 者 ×0.05 地板，20 倍 handicap，与 time_note"日期未知按最早资格处理"矛盾）。
        # 重加权 0.5+0.5×norm：未知=最早（×0.5）、最新 ×1.0，单调、有界、仅作用排序（F4）。
        scored.sort(reverse=True)
        # R04-01 v2（用户 2026-10-22 指示：文档与代码分别命中后再融合，而非一路独占）：
        # 三路（code/doc/knowledge）各自完成 fam 去重与路内断崖精剪，融合时每条非空路
        # 保底入席（code/doc ≤2、kn ≤1），其余席位按全局分补足。旧全局断崖使巨型泛词
        # 文档独占结果（product-llm-enrich-hardening A/B 实证：代码路与 Knowledge 笔记
        # 同时被剪光）——精度守门保留，比较对象从全局 top 改为路内 top。
        def _lane_of(nid):
            kind = self._node(nid)["kind"]
            if kind == "Knowledge":
                return "kn"
            return "doc" if kind == "Doc" else "code"

        def _lane_prepare(pairs):
            """路内：同文件 ≤2 席（防 seeds/README 型噪声霸榜）+ 断崖精剪（<45% 路内 top 截尾）。"""
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

        lanes = {"code": [], "doc": [], "kn": []}
        for s, nid in scored:
            lanes[_lane_of(nid)].append((s, nid))
        lanes = {k: _lane_prepare(v) for k, v in lanes.items() if v}
        guaranteed, taken = [], set()
        for lane, cap in (("code", 2), ("doc", 2), ("kn", 1)):
            for item in lanes.get(lane, [])[:cap]:
                guaranteed.append(item)
                taken.add(item[1])
        rest = sorted((x for lane in lanes.values() for x in lane if x[1] not in taken),
                      reverse=True)
        merged = sorted(guaranteed + rest, reverse=True)[:top_k]
        # 保底落位：保证席位被高分挤出 top_k 时，替换尾部非保证项（每条非空路必有代表）
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
        # 跨族覆盖：若得分前 20 的其它族（文件根）在 top_k 无代表，用该族最佳替换尾部最低分
        # （全局最佳与保底席位始终保留；替换按族头得分与被替项得分顺序进行）
        pool = sorted((x for lane in lanes.values() for x in lane), reverse=True)[:max(20, top_k)]
        sel_fams = {self._node(nid)["file"].split("/", 1)[0] for _, nid in merged}
        for sc, nid in pool:
            fseg = self._node(nid)["file"].split("/", 1)[0]
            if fseg in sel_fams:
                continue
            if (len(merged) >= top_k and sc > merged[-1][0]
                    and merged[-1][1] not in gua_ids):  # 保底席位不被跨族交换挤掉
                merged[-1] = (sc, nid)
            elif len(merged) < top_k:
                merged.append((sc, nid))
            else:
                break
            sel_fams.add(fseg)
            merged.sort(reverse=True)
        seeds = merged[:top_k]
        seed_ids = [nid for _, nid in seeds]
        seen = set(seed_ids)
        lines = ["## 种子命中（词法 IDF）"]
        for idx, (s, nid) in enumerate(seeds):
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
        if n["meta"].get("domain"):
            head += "  [域:%s%s]" % (n["meta"]["domain"], "/vote" if n["meta"].get("domain_by") else "")
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
