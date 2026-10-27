"""graph — 统一图构建：records → nodes/edges（带置信+provenance）→ 领域打标 → 落盘。

图 Schema（方案 §04 的 lite 实装）：
  节点 kind：Service/Class/Method/Route/Table/Column/Topic/SqlStmt/Doc/Page/Domain
  边 kind：CONTAINS/HANDLES/ROUTES_TO/CALLS_SQL/READS/WRITES/PUBLISHES/SUBSCRIBES/RPC/MENTIONS/BELONGS_TO
"""
import json
import os
from collections import Counter, defaultdict

from . import lite_scan
from .tokenize import tokenize

CONF_ORDER = {"EXTRACTED": 3, "INFERRED": 2, "AMBIGUOUS": 1}
# 因果边：影响面遍历只走这些；MENTIONS（词面）/BELONGS_TO（领域归属）/CONTAINS（结构）不冒充依赖
CAUSAL_EDGES = frozenset({"CALLS", "CALLS_SQL", "READS", "WRITES", "RPC", "PUBLISHES",
                          "SUBSCRIBES", "ROUTES_TO", "HANDLES", "MAPS_TO"})

class Graph:
    def __init__(self):
        self.nodes = {}          # id -> node dict
        self.edges = []          # {src,dst,kind,conf,prov}
        self._adj = defaultdict(list)
        self._radj = defaultdict(list)
        self._built = False
        self.sig = None          # load() 来源图的 (mtime, size) 指纹，供 Searcher 索引缓存门控

    # ---------- 基础 ----------
    def add_node(self, nid, kind, name, file, meta=None, conf="EXTRACTED", prov="core"):
        if nid in self.nodes:
            self.nodes[nid]["meta"].update(meta or {})
            return nid
        self.nodes[nid] = {"id": nid, "kind": kind, "name": name, "file": file,
                           "meta": meta or {}, "conf": conf, "prov": prov}
        return nid

    def add_edge(self, src, dst, kind, conf="INFERRED", prov="core"):
        if src not in self.nodes or dst not in self.nodes:
            return
        self.edges.append({"src": src, "dst": dst, "kind": kind, "conf": conf, "prov": prov})

    def index(self):
        self._adj.clear(); self._radj.clear()
        for e in self.edges:
            self._adj[e["src"]].append(e)
            self._radj[e["dst"]].append(e)
        self._built = True

    def neighbors(self, nid, rev=False):
        if not self._built:
            self.index()
        return (self._radj if rev else self._adj).get(nid, [])

    # ---------- 构建 ----------
    @staticmethod
    def _mth_id(service, cls, name, sig):
        """方法身份含完整参数类型签名（RV02）：同参数数量的重载不再合并；签名未知（跨行声明）记 "?"。"""
        return "mth:%s:%s.%s(%s)" % (service, cls or "-", name, sig if sig is not None else "?")

    def _mth_declare(self, service, cls, name, sig, argc, meta_extra, file, prov):
        nid = self._mth_id(service, cls, name, sig)
        self.add_node(nid, "Method", name, file,
                      {"line": meta_extra.get("line"), "cls": cls or "", "argc": argc, **meta_extra},
                      conf="EXTRACTED", prov=prov)
        self._mth_index.setdefault((service, cls or "-", name), []).append((nid, argc))
        return nid

    def _mth_candidates(self, service, cls, name, argc):
        """按 (svc, cls, name, argc) 解析候选重载（RV02）。argc=-1（未知）→ 全部候选（不确定，不猜）。"""
        cands = self._mth_index.get((service, cls or "-", name), [])
        if argc is None or argc < 0:
            return [nid for nid, _ in cands]
        return [nid for nid, a in cands if a == argc]

    @staticmethod
    def _topic_cluster(prov):
        """消息集群 = 声明的数据源家族（RV02b）：rocketmq/kafka/rabbit/jms/stream；无法判定 → unknown。"""
        p = (prov or "").lower()
        if "rocketmq" in p:
            return "rocketmq"
        for fam in ("kafka", "rabbit", "jms", "stream"):
            if fam in p:
                return fam
        return "unknown"

    def _topic_declare(self, rec):
        """Topic 按消息集群隔离（RV02b）：ID=topic:<cluster>:<name>。

        同集群同名跨服务连接为一个节点——共享依据=「相同声明的数据源家族 + 相同主题名」（pub/sub 按名对接
        的真实机制），参与方服务列表排序确定（顺序无关）；不同集群同名保持独立，之间无任何共享边。
        """
        cluster = self._topic_cluster(rec.get("prov"))
        name = rec["topic"]
        tid = "topic:%s:%s" % (cluster, name)
        existing = self.nodes.get(tid)
        if existing is None:
            self.add_node(tid, "Topic", name, rec["file"],
                          {"cluster": cluster, "services": [],
                           "shared_basis": "same declared datasource family (%s) + same topic name" % cluster,
                           **self._sid(rec)},
                          conf=rec.get("conf", "EXTRACTED"), prov=rec.get("prov", "core"))
            existing = self.nodes[tid]
        services = set(existing["meta"].get("services") or []) | {rec["service"]}
        existing["meta"]["services"] = sorted(services)  # 确定性：与构建顺序无关
        return tid

    def _tbl_declare(self, service, name, file, meta, conf="EXTRACTED", prov="sql:ddl"):
        """表/列按声明方服务隔离（RV02）：tbl:<svc>:<name>；同名跨仓不再合并，引用经 _tbl_ref 显式连接。"""
        tid = "tbl:%s:%s" % (service, name)
        self.add_node(tid, "Table", name, file, meta, conf=conf, prov=prov)
        self._tbl_index.setdefault(name, []).append(tid)
        return tid

    def _tbl_ref(self, service, name, file):
        """按名引用一张表（RV02）：只在**已声明**的表中找候选——单候选→显式连接；多候选→逐条 AMBIGUOUS（不合并）。

        无声明时在本服务作用域建不确定节点，且**不**注册进名字索引：其他服务不得连接到
        一个未声明的推断节点（否则首个被扫描的服务决定归属，构建顺序影响身份）。
        同服务内多个 mapper 引用同名未声明表 → 同一作用域节点（确定性合并）。
        """
        cands = self._tbl_index.get(name, [])
        if not cands:
            return ["tbl:%s:%s" % (service, name)], True
        return cands, False

    @staticmethod
    def _sid(rec):
        """记录级来源身份（build_many 戳入 label|rel）；旧记录无 sid 时为空（D11 兼容）。"""
        return {"sid": rec["sid"]} if rec.get("sid") else {}

    def build_from_records(self, R, seeds):
        self._mth_index = {}
        self._tbl_index = {}
        dom_of_service = {}
        for svc, info in R["services"].items():
            self.add_node("svc:" + svc, "Service", svc, info.get("file", svc), {"classes": info.get("classes", 0)})
        # DDL 表：按声明方服务隔离（RV02）；列跟随所属表的作用域
        for t in R["tables"]:
            svc = t.get("service") or "(root)"
            tid = self._tbl_declare(svc, t["table"], t["file"],
                                    {"cols": t["cols"], **self._sid(t)}, conf=t["conf"], prov=t["prov"])
            for c in t["cols"]:
                cid = self.add_node("col:%s:%s.%s" % (svc, t["table"], c), "Column", c, t["file"],
                                    {}, conf="EXTRACTED", prov="sql:ddl")
                self.add_edge(tid, cid, "CONTAINS", "EXTRACTED", "sql:ddl")
        # 类/方法
        for c in R["classes"]:
            cid = self.add_node("cls:%s:%s" % (c["service"], c["fqn"]), "Class", c["name"], c["file"],
                                {"rest": c["rest_controller"], "dubbo": c["dubbo_service"],
                                 "comment": c.get("comment", ""), **self._sid(c)},
                                conf="EXTRACTED", prov=c["prov"])
            self.add_edge("svc:" + c["service"], cid, "CONTAINS", "EXTRACTED", "java")
        for m in R["methods"]:
            meta = {"line": m.get("line"), "argc": m.get("argc", -1), **self._sid(m)}
            if m.get("sig") is None:
                meta["sig_unknown"] = True  # 跨行签名未解析：身份带 ?，显式不确定
            mid = self._mth_declare(m["service"], m.get("cls"), m["name"], m.get("sig"),
                                    m.get("argc", -1), meta, m["file"], m["prov"])
            self.add_edge("svc:" + m["service"], mid, "CONTAINS", "EXTRACTED", "java")
        # 方法级调用（lite 正则合成；Method 节点 service 级命名，同名方法跨类共点的限制待 AST 引擎解决）
        for c in R.get("calls", []):
            # 调用侧签名未知：按 argc 匹配候选重载；多候选逐条 AMBIGUOUS（不确定保留，不合并）
            for src in self._mth_candidates(c["service"], c.get("from_cls"), c["from"], c.get("from_argc", -1)):
                for argc in c.get("to_argcs", [-1]):
                    dsts = self._mth_candidates(c["service"], c.get("to_cls"), c["to_method"], argc)
                    conf = c["conf"] if len(dsts) <= 1 else "AMBIGUOUS"
                    for dst in dsts:
                        if dst != src:
                            self.add_edge(src, dst, "CALLS", conf, c["prov"])
        # Spring 路由
        for r in R["routes"]:
            # 路由/SQL/页面 ID 带服务限定（含仓标签前缀）：跨仓同路径/同 iface.id 不再合并（D11）
            rid = self.add_node("route:%s:%s %s" % (r["service"], r["method"], r["path"]), "Route",
                                "%s %s" % (r["method"], r["path"]), r["file"], self._sid(r),
                                conf=r["conf"], prov=r["prov"])
            for mid in self._mth_candidates(r["service"], r.get("cls"), r["java_method"], r.get("argc", -1)):
                self.add_edge(mid, rid, "HANDLES", r["conf"], r["prov"])
        # MyBatis：SQL 语句 + 接口方法桥 + 表/列读写
        for s in R["sqlstmts"]:
            sid = self.add_node("sql:%s:%s.%s" % (s["service"], s["iface"], s["id"]), "SqlStmt",
                                "%s.%s" % (s["iface"], s["id"]), s["file"],
                                {"verb": s["verb"], "sql": s["sql"], **self._sid(s)}, conf=s["conf"], prov=s["prov"])
            for mid in self._mth_candidates(s["service"], s["iface"], s["id"], None):
                self.add_edge(mid, sid, "CALLS_SQL", s["conf"], s["prov"])
            for t in s["tables"]:
                cands, unresolved = self._tbl_ref(s["service"], t, s["file"])
                if unresolved:
                    for tid in cands:
                        self.add_node(tid, "Table", t, s["file"],
                                      {"via": "mapper", "unresolved": True, **self._sid(s)},
                                      conf="EXTRACTED", prov="synth:mybatis")
                conf = s["conf"] if len(cands) <= 1 else "AMBIGUOUS"
                for tid in cands:
                    self.add_edge(sid, tid,
                                  "WRITES" if s["verb"] in {"INSERT", "UPDATE", "DELETE"} else "READS",
                                  conf, s["prov"])
        # JPA 实体：@Table 是声明（按实体所属服务隔离）；@Column 列跟随该作用域（RV02）
        for en in R.get("entities", []):
            tid = self._tbl_declare(en["service"], en["table"], en["file"],
                                    {"via": "jpa"}, conf=en["conf"], prov=en["prov"])
            for c in en["cols"]:
                cid = self.add_node("col:%s:%s.%s" % (en["service"], en["table"], c), "Column", c,
                                    en["file"], {}, conf=en["conf"], prov=en["prov"])
                self.add_edge(tid, cid, "CONTAINS", en["conf"], en["prov"])
            for n in list(self.nodes.values()):
                if n["kind"] == "Class" and n["name"] == en["cls"]:
                    self.add_edge(n["id"], tid, "MAPS_TO", en["conf"], en["prov"])
                    break
        # MQ Topic：按消息集群隔离（RV02b）——同集群同名连接（显式共享依据），跨集群同名独立
        for t in sorted(R["topics"], key=lambda x: (x["topic"], x["service"], x["file"])):
            tid = self._topic_declare(t)
            mids = self._mth_candidates(t["service"], t.get("cls"), t["by"], t.get("argc", -1))
            src = mids[0] if len(mids) == 1 else ("svc:" + t["service"])
            if t["dir"] == "PUBLISHES":
                self.add_edge(src, tid, "PUBLISHES", t["conf"], t["prov"])
            else:
                self.add_edge(tid, src, "SUBSCRIBES", t["conf"], t["prov"])
        # Dubbo/Feign RPC（按接口名对齐生产/消费；缺一侧仍记录挂起引用）
        provs = {}
        for r in R["rpc"]:
            provs.setdefault(r["iface"], {"consumers": set(), "providers": []})
            provs[r["iface"]]["consumers"].add(r["service"])
        for c in R["classes"]:
            if c["dubbo_service"] and c["name"] in provs:
                provs[c["name"]]["providers"].append(c["service"])
        for iface, info in provs.items():
            multi = len(set(info["providers"])) > 1
            for cons in info["consumers"]:
                for pid in set(info["providers"]):
                    if pid != cons:
                        self.add_edge("svc:" + cons, "svc:" + pid, "RPC",
                                      "AMBIGUOUS" if multi else "INFERRED",
                                      "synth:dubbo+multi-provider" if multi else "synth:dubbo")
        # 跨端连线：page 调用 → 后端 Route（URL 精确→前缀匹配，method 兼容）
        routes = [n for n in self.nodes.values() if n["kind"] == "Route"]
        for p in R["pages"]:
            pid = self.add_node("page:%s:%s" % (p["service"], p["url"]), "Page", p["url"], p["file"],
                                {"method": p["method"], **self._sid(p)}, conf=p["conf"], prov=p["prov"])
            hit = None
            for rt in routes:
                rp = rt["name"].split(" ", 1)[1]
                if p["url"] == rp or (rp and p["url"].startswith(rp)):
                    hit = rt
                    break
            if hit:
                self.add_edge(pid, hit["id"], "ROUTES_TO", p["conf"], "synth:crossend")
        # 文档 + MENTIONS（词面命中代码符号，INFERRED）
        names_idx = {}
        for n in self.nodes.values():
            if n["kind"] in {"Service", "Class", "Table", "Topic"}:
                for tk in set(tokenize(n["name"])):
                    if len(tk) > 2 or ord(tk[0]) > 0x2e80:
                        names_idx.setdefault(tk, set()).add(n["id"])
        for d in R["docs"]:
            did = self.add_node("doc:%s:%s" % (d.get("service", "(root)"), d["path"]), "Doc",
                                os.path.basename(d["path"]), d["path"],
                                {"text": d["text"],
                                 # 纪元：正文自述日期 > 内容首次收录（复制/touch 不刷新）> 文件 mtime（仅旧记录）
                                 "first_seen": d.get("content_era") or d.get("content_first_seen") or d.get("mtime") or 0.0,
                                 "era_source": ("content" if d.get("content_era")
                                                else "store" if d.get("content_first_seen") else "mtime"),
                                 **{k: d[k] for k in ("valid_until", "superseded_by") if d.get(k)},
                                 **self._sid(d)},
                                conf="EXTRACTED", prov="doc:ingest")
            hits = Counter()
            for tk in tokenize(d["text"]):
                for nid in names_idx.get(tk, ()):  # 词面命中
                    hits[nid] += 1
            for nid, c in hits.most_common(12):
                if c >= 2:
                    self.add_edge(did, nid, "MENTIONS", "AMBIGUOUS", "doc:lexical")
        # 领域打标
        self.tag_domains(seeds)
        self.index()

    # ---------- 领域 ----------
    def tag_domains(self, seeds, vote=True):
        dom_nodes = {}
        for dom, spec in seeds.items():
            if dom.startswith("_"):
                continue
            dom_nodes[dom] = self.add_node("dom:" + dom, "Domain", dom, "seeds.json",
                                           {"keywords": spec.get("keywords", [])}, conf="EXTRACTED", prov="seed")
        def match_dom(text):
            tl = text.lower()
            for dom, spec in seeds.items():
                if dom.startswith("_"):
                    continue
                for kw in spec.get("keywords", []):
                    if kw.lower() in tl:
                        return dom
            for dom, spec in seeds.items():
                for pfx in spec.get("prefixes", []):
                    if tl.startswith(pfx.lower()):
                        return dom
            return None
        # 服务/表/主题 先验
        for n in list(self.nodes.values()):
            if n["kind"] in {"Service", "Table", "Topic"}:
                d = match_dom(n["name"])
                if d:
                    n["meta"]["domain"] = d
                    self.add_edge("dom:" + d, n["id"], "BELONGS_TO", "EXTRACTED", "seed")
        # 类/方法/列 继承（经由 CONTAINS 上游服务）
        if vote:
            for n in list(self.nodes.values()):
                if "domain" in n["meta"] or n["kind"] in {"Domain", "Doc", "Page"}:
                    continue
                votes = Counter()
                for e in self.neighbors(n["id"], rev=True) + self.neighbors(n["id"]):
                    other = e["dst"] if e["src"] == n["id"] else e["src"]
                    d = self.nodes.get(other, {}).get("meta", {}).get("domain")
                    if d:
                        votes[d] += 1
                if votes:
                    d, c = votes.most_common(1)[0]
                    if c >= 2 or len(votes) == 1:
                        n["meta"]["domain"] = d
                        n["meta"]["domain_by"] = "vote"
                        self.add_edge("dom:" + d, n["id"], "BELONGS_TO", "INFERRED", "vote")

    def domain_map(self):
        agg = defaultdict(lambda: {"services": [], "tables": [], "topics": [], "docs": 0, "shared": []})
        for n in self.nodes.values():
            d = n["meta"].get("domain")
            if not d:
                continue
            a = agg[d]
            if n["kind"] == "Service":
                a["services"].append(n["name"])
            elif n["kind"] == "Table":
                a["tables"].append(n["name"])
            elif n["kind"] == "Topic":
                a["topics"].append(n["name"])
            elif n["kind"] == "Doc":
                a["docs"] += 1
        # 跨域共享表：同一 Table 被不同域服务读写（按 sqlstmt 的 service 域）
        tbl_writers = defaultdict(set)
        for n in self.nodes.values():
            if n["kind"] == "SqlStmt":
                d = n["meta"].get("domain")
                for e in self.neighbors(n["id"]):
                    t = self.nodes.get(e["dst"])
                    if t and t["kind"] == "Table" and d:
                        tbl_writers[t["name"]].add(d)
        for t, doms in tbl_writers.items():
            if len(doms) > 1:
                agg["__shared__"]["shared"].append({"table": t, "domains": sorted(doms)})
        return dict(agg)

    # ---------- 影响面 ----------
    def impact(self, name, depth=2, max_nodes=None):
        """反向影响面（只走因果边：MENTIONS/BELONGS_TO/CONTAINS 不冒充依赖，roadmap M2）。

        max_nodes 在遍历中执行（达到即停，非先算全量再截断）。
        每条结果为 (src 节点, 边类型, dst 节点, 路径强度)；路径强度 = 该路径最弱边的置信
        （路径强度不高于最弱边）。BFS 首达路径决定强度。
        """
        start = [n for n in self.nodes.values() if name.lower() in n["id"].lower()]
        seen, frontier, out = set(), set(start and [n["id"] for n in start] or []), []
        strength = {nid: "EXTRACTED" for nid in frontier}  # 起点自身无路径约束
        for _ in range(depth):
            nxt = set()
            for nid in frontier:
                for e in self.neighbors(nid, rev=True):  # 反向：谁依赖我
                    if e["kind"] not in CAUSAL_EDGES:
                        continue  # 词面提及/领域归属/结构包含不是因果依赖
                    if e["src"] not in seen:
                        path_strength = min((strength[nid], e["conf"]), key=lambda c: CONF_ORDER.get(c, 0))
                        seen.add(e["src"]); nxt.add(e["src"])
                        strength[e["src"]] = path_strength
                        out.append((self.nodes[e["src"]], e["kind"], self.nodes[nid], path_strength))
                        if max_nodes is not None and len(out) >= max_nodes:
                            return start, out
            frontier = nxt
        return start, out

    # ---------- 持久化 ----------
    def save(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"nodes": list(self.nodes.values()), "edges": self.edges,
                       "schema": "domimap.lite.v1"}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)

    @classmethod
    def load(cls, path):
        g = cls()
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        g.nodes = {n["id"]: n for n in d["nodes"]}
        g.edges = d["edges"]
        st = os.stat(path)
        g.sig = {"mtime": st.st_mtime, "size": st.st_size}
        g.index()
        return g

def load_seeds(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def build(repo_root, out_dir, seeds_path=None):
    """单仓构建：与批量路径共用同一证据契约（扫描即固化 → 不可变代 → graph.json → manifest）。

    服务不加仓名前缀（单仓既有命名，写入 manifest.service_prefix=None 供 update 沿用）。
    seeds_path 保留签名兼容；种子统一取包内 seeds.json（与 build_many 一致）。
    """
    from .batch import build_many
    root = os.path.abspath(repo_root)
    g, cov, _ = build_many([root], out_dir, force=True,
                           merged_name=os.path.basename(os.path.abspath(out_dir)) or "repo",
                           service_prefixes={root: None})
    return g, cov
