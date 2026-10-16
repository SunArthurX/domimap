"""scenario — 三场景中的 A/B 命令化（C=domain 命令已有）。

场景A 需求识别：需求文本 → 领域分类 → 服务/接口/表/MQ/文档定位卡 + 建议路径。
场景B 问题排查：症状 → 图+文档双路召回 → 文档摘句 → 疑点排序（静态边；观测边待接入）。
"""
from collections import Counter

from .search import Searcher

KIND_PRIORITY = {"Table": 0, "SqlStmt": 1, "Topic": 2, "Method": 3, "Service": 4, "Route": 5, "Class": 6}

def classify(text, seeds):
    """需求文本 → 命中领域列表（按命中种子词数排序）。"""
    units = Searcher._units(text)
    hits = Counter()
    for dom, spec in seeds.items():
        if dom.startswith("_"):
            continue
        kws = set()
        for kw in spec.get("keywords", []):
            kws.update(Searcher._units(kw))
        for pfx in spec.get("prefixes", []):
            kws.update(Searcher._units(pfx))
        n = len(units & kws)
        if n:
            hits[dom] = n
    return [d for d, _ in hits.most_common()]

def scenario_req(g, s, text, seeds, top=10):
    doms = classify(text, seeds)
    lines = ["# 需求定位卡", "", "识别领域：" + ("、".join(doms) if doms else "未命中种子（将全图检索）"), ""]
    # 查询期领域词表同义词扩展：命中域的英文种子词拼进检索（纯代码仓中文词面不匹配的兜底）
    qtext = text
    if doms:
        ext = []
        for d in doms:
            ext.extend(seeds[d].get("keywords", [])[:6])
            ext.extend(seeds[d].get("prefixes", [])[:4])
        qtext = text + " " + " ".join(ext)
        lines.append("> 已扩展检索词（领域词表）：" + " ".join(ext[:8]) + " …")
        lines.append("")
    buckets = {k: [] for k in ("Service", "Route", "Table", "Topic", "Doc", "SqlStmt")}
    r = s.query(qtext, top_k=top, expand=False)
    for n in r["seeds"]:
        if n["kind"] in buckets and all(n["id"] != b["id"] for b in buckets[n["kind"]]):
            buckets[n["kind"]].append(n)
    for kind in ("Service", "Route", "Table", "Topic", "SqlStmt", "Doc"):
        items = buckets[kind][:8]
        if not items:
            continue
        lines.append("## " + {"Service": "涉及服务", "Route": "相关接口", "Table": "涉及表",
                              "Topic": "MQ 主题", "SqlStmt": "关键 SQL", "Doc": "关联文档"}[kind])
        for n in items:
            lines.append("- %s  @%s  [%s/%s]" % (n["name"], n["file"], n["conf"], n["meta"].get("domain", "")))
        lines.append("")
    # 建议路径：top 服务 → 其路由/SQL/表（图上 2 跳）
    if buckets["Service"]:
        svc = buckets["Service"][0]
        lines.append("## 建议改动路径（从 %s 出发）" % svc["name"])
        for e in g.neighbors(svc["id"]) + g.neighbors(svc["id"], rev=True):
            other = g.nodes.get(e["dst"] if e["src"] == svc["id"] else e["src"])
            if other and other["kind"] in {"Route", "SqlStmt", "Topic", "Table", "Class"}:
                lines.append("- %s --%s(%s)--> %s" % (svc["name"], e["kind"], e["conf"], other["name"]))
        lines.append("\n> 下一步：domimap impact %s -g <图> 看反向影响面；上线前过 关联文档 的 checklist。" % svc["name"])
    return "\n".join(lines)

def _snippets(node, units, max_n=3):
    out = []
    text = node["meta"].get("text", "")
    strong = {u for u in units if len(u) >= 2}
    if not text:
        return out
    for ln in text.split("\n"):
        low = ln.lower()
        if any(u in low or u in ln for u in strong):
            t = ln.strip()
            if 0 < len(t) < 200:
                out.append(t)
                if len(out) >= max_n:
                    break
    return out

def scenario_trb(g, s, symptom):
    units = Searcher._units(symptom)
    # 症状文本噪声大：排障走更宽容的覆盖率门槛（≥15% 或强命中），拒答条件不变
    r = s.query(symptom, top_k=10, expand=True, min_cov=0.15)
    lines = ["# 排障卡（静态图 + 文档 双路召回）",
             "", "> 观测边(OBSERVED_CALLS)待 SkyWalking 接入；当前为静态调用链 + 历史文档/工单。", ""]
    docs = [n for n in r["seeds"] if n["kind"] == "Doc"]
    if docs:
        lines.append("## 文档命中（含摘句）")
        for d in docs[:5]:
            lines.append("- %s @%s" % (d["name"], d["file"]))
            for sn in _snippets(d, units):
                lines.append("    > " + sn)
        lines.append("")
    graph_hits = [n for n in r["seeds"] if n["kind"] in KIND_PRIORITY]  # 排除 Domain/Doc 噪声
    graph_hits.sort(key=lambda n: (KIND_PRIORITY.get(n["kind"], 9),))
    if graph_hits:
        lines.append("## 图命中（疑点排序：表>SQL>主题>方法>服务）")
        for n in graph_hits[:8]:
            dep_cnt = len(g.neighbors(n["id"], rev=True))
            lines.append("- [%s] %s @%s  (被依赖 %d 处, %s/%s)" %
                         (n["kind"], n["name"], n["file"], dep_cnt, n["conf"], n["meta"].get("domain", "")))
        lines.append("")
    if r.get("refused"):
        lines.insert(2, "⚠ " + r["text"])
    lines.append("## 建议动作")
    lines.append("- 对表/SQL 命中：domimap impact <表名> 查反向依赖，确认影响面")
    lines.append("- 对方法命中：阅读 @file 上下文，查同 Topic 的生产/消费两端")
    lines.append("- 若文档命中有 checklist：按其逐项核对")
    return "\n".join(lines)
