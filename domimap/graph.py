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
    def _sid(rec):
        """记录级来源身份（build_many 戳入 label|rel）；旧记录无 sid 时为空（D11 兼容）。"""
        return {"sid": rec["sid"]} if rec.get("sid") else {}

    def build_from_records(self, R, seeds):
        dom_of_service = {}
        for svc, info in R["services"].items():
            self.add_node("svc:" + svc, "Service", svc, info.get("file", svc), {"classes": info.get("classes", 0)})
        # DDL 表
        for t in R["tables"]:
            self.add_node("tbl:" + t["table"], "Table", t["table"], t["file"],
                          {"cols": t["cols"], **self._sid(t)}, conf=t["conf"], prov=t["prov"])
            for c in t["cols"]:
                cid = self.add_node("col:%s.%s" % (t["table"], c), "Column", c, t["file"], {}, conf="EXTRACTED", prov="sql:ddl")
                self.add_edge("tbl:" + t["table"], cid, "CONTAINS", "EXTRACTED", "sql:ddl")
        # 类/方法
        for c in R["classes"]:
            cid = self.add_node("cls:%s:%s" % (c["service"], c["fqn"]), "Class", c["name"], c["file"],
                                {"rest": c["rest_controller"], "dubbo": c["dubbo_service"],
                                 "comment": c.get("comment", ""), **self._sid(c)},
                                conf="EXTRACTED", prov=c["prov"])
            self.add_edge("svc:" + c["service"], cid, "CONTAINS", "EXTRACTED", "java")
        for m in R["methods"]:
            mid = self.add_node("mth:%s:%s.%s#%s" % (m["service"], m.get("cls") or "-",
                                                      m["name"], m.get("argc", -1)),
                                "Method", m["name"], m["file"],
                                {"line": m.get("line"), "cls": m.get("cls") or "",
                                 "argc": m.get("argc", -1), **self._sid(m)},
                                conf="EXTRACTED", prov=m["prov"])
            self.add_edge("svc:" + m["service"], mid, "CONTAINS", "EXTRACTED", "java")
        # 方法级调用（lite 正则合成；Method 节点 service 级命名，同名方法跨类共点的限制待 AST 引擎解决）
        for c in R.get("calls", []):
            src = "mth:%s:%s.%s#%s" % (c["service"], c.get("from_cls") or "-",
                                       c["from"], c.get("from_argc", -1))
            if src not in self.nodes:
                continue
            for argc in c.get("to_argcs", [-1]):  # 重载多候选：逐候选连边，置信随 dispatch 已知性
                dst = "mth:%s:%s.%s#%s" % (c["service"], c.get("to_cls") or "-", c["to_method"], argc)
                if dst in self.nodes and dst != src:
                    self.add_edge(src, dst, "CALLS", c["conf"], c["prov"])
        # Spring 路由
        for r in R["routes"]:
            # 路由/SQL/页面 ID 带服务限定（含仓标签前缀）：跨仓同路径/同 iface.id 不再合并（D11）
            rid = self.add_node("route:%s:%s %s" % (r["service"], r["method"], r["path"]), "Route",
                                "%s %s" % (r["method"], r["path"]), r["file"], self._sid(r),
                                conf=r["conf"], prov=r["prov"])
            mid = "mth:%s:%s.%s#%s" % (r["service"], r.get("cls") or "-",
                                        r["java_method"], r.get("argc", -1))
            if mid in self.nodes:
                self.add_edge(mid, rid, "HANDLES", r["conf"], r["prov"])
        # MyBatis：SQL 语句 + 接口方法桥 + 表/列读写
        for s in R["sqlstmts"]:
            sid = self.add_node("sql:%s:%s.%s" % (s["service"], s["iface"], s["id"]), "SqlStmt",
                                "%s.%s" % (s["iface"], s["id"]), s["file"],
                                {"verb": s["verb"], "sql": s["sql"], **self._sid(s)}, conf=s["conf"], prov=s["prov"])
            for m in R["methods"]:  # DAO 接口方法（同名，重载逐版本桥接）
                if m["service"] == s["service"] and m.get("cls") == s["iface"] and m["name"] == s["id"]:
                    mid = "mth:%s:%s.%s#%s" % (m["service"], m["cls"], m["name"], m.get("argc", -1))
                    self.add_edge(mid, sid, "CALLS_SQL", s["conf"], s["prov"])
            for t in s["tables"]:
                # 表节点缺失先建（真实语料常无 DDL：先连边后补节点会全丢，真实任务回放发现的排序缺陷）
                self.add_node("tbl:" + t, "Table", t, s["file"], {"via": "mapper"},
                              conf="EXTRACTED", prov="synth:mybatis")
                self.add_edge(sid, "tbl:" + t,
                              "WRITES" if s["verb"] in {"INSERT", "UPDATE", "DELETE"} else "READS",
                              s["conf"], s["prov"])
        # MyBatis 表也补进 Table 节点（DDL 未覆盖时）
        for s in R["sqlstmts"]:
            for t in s["tables"]:
                self.add_node("tbl:" + t, "Table", t, s["file"], {"via": "mapper"}, conf="EXTRACTED", prov="synth:mybatis")
        # JPA 实体：@Table 表 + @Column 列 + 实体类 MAPS_TO 表
        for en in R.get("entities", []):
            self.add_node("tbl:" + en["table"], "Table", en["table"], en["file"],
                          {"via": "jpa"}, conf=en["conf"], prov=en["prov"])
            for c in en["cols"]:
                cid = self.add_node("col:%s.%s" % (en["table"], c), "Column", c, en["file"],
                                    {}, conf=en["conf"], prov=en["prov"])
                self.add_edge("tbl:" + en["table"], cid, "CONTAINS", en["conf"], en["prov"])
            for n in list(self.nodes.values()):
                if n["kind"] == "Class" and n["name"] == en["cls"]:
                    self.add_edge(n["id"], "tbl:" + en["table"], "MAPS_TO", en["conf"], en["prov"])
                    break
        # MQ Topic
        for t in R["topics"]:
            tid = self.add_node("topic:" + t["topic"], "Topic", t["topic"], t["file"], {}, conf=t["conf"], prov=t["prov"])
            _mid = "mth:%s:%s.%s#%s" % (t["service"], t.get("cls") or "-",
                                         t["by"], t.get("argc", -1))
            src = _mid if _mid in self.nodes else "svc:" + t["service"]
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
        """反向影响面。max_nodes 在遍历中执行（达到即停，非先算全量再截断）。"""
        start = [n for n in self.nodes.values() if name.lower() in n["id"].lower()]
        seen, frontier, out = set(), set(start and [n["id"] for n in start] or []), []
        for _ in range(depth):
            nxt = set()
            for nid in frontier:
                for e in self.neighbors(nid, rev=True):  # 反向：谁依赖我
                    if e["src"] not in seen:
                        seen.add(e["src"]); nxt.add(e["src"])
                        out.append((self.nodes[e["src"]], e["kind"], self.nodes[nid]))
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
