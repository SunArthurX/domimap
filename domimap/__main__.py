#!/usr/bin/env python3
"""domimap CLI — 多仓 Java 知识中台（可执行 MVP）。

命令：
  doctor                     环境自检（平台/可选依赖/图谱状态）
  build <repo...> -o DIR     扫描仓库 → 统一图 graph.json + coverage.json
                             （--merge 单仓直出到 -o 目录；--discover 把参数视为工作区根，
                             自动发现子仓合并建图，并生成证据库 store.db 与增量清单）
  update -o DIR              工作区增量重建（manifest 未变时毫秒级 no-op）
  query "文本" -g FILE        混合检索（词法种子+一跳图扩展；诚实拒答时退出码 3）
  domain -g FILE             领域地图（含跨域共享表）
  impact <符号> -g FILE      影响面（反向依赖）
  read <ev_id> --store DB    按证据 ID 读固化片段（源修改/删除后仍为旧版本）
  scenario req|trb "文本"    需求定位卡 / 问题排查卡
  review -g FILE -o DIR      AMBIGUOUS 边导出 Obsidian 待审页（人审双通道）
  enrich -g FILE [--limit N] 可选 LLM 语义增强：Doc 材料生成 inference 草稿笔记
                             （--dry-run/--force/--model/--endpoint；key 走 GLM_API_KEY 等
                             环境变量，未配置退出码 6；产物标注 conf=LLM 不混入事实）
  serve -g FILE              MCP stdio 服务器（kg_explore 等 6 工具）
  ui -g FILE [--port N]      本地只读搜索/证据阅读页（默认 127.0.0.1:8765）
"""
import argparse
import json
import os
import platform
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from domimap import __version__  # noqa: E402

def cmd_doctor(args):
    print("domimap %s doctor" % __version__)
    print("  平台: %s / %s / Python %s" % (platform.system(), platform.machine(), platform.version()))
    for mod, tip in [("jieba", "中文分词增强（未装则用内建 CJK n-gram 兜底）"),
                     ("docx", ".docx 文档摄入（python-docx）"),
                     ("pypdf", ".pdf 文档摄入（pypdf）"),
                     ("graphify", "全量 AST 引擎（repos/graphify 源 + 依赖）")]:
        try:
            __import__(mod)
            print("  [OK] %-10s" % mod)
        except ImportError:
            print("  [--] %-10s %s" % (mod, tip))
    g = args.graph
    if g and os.path.exists(g):
        d = json.load(open(g, encoding="utf-8"))
        print("  图谱: %d 节点 / %d 边 / schema=%s" % (len(d["nodes"]), len(d["edges"]), d.get("schema")))
    else:
        print("  图谱: 尚未构建（domimap build <仓库目录> -o out/<名字>）")

def cmd_build(args):
    from domimap.graph import build
    from domimap.batch import discover_roots, build_many
    if args.discover:
        roots = discover_roots(args.repos[0])
        if not roots:
            print("未发现子仓（需含 pom.xml/build.gradle/.git/package.json）"); sys.exit(4)
        print("发现 %d 个仓：%s" % (len(roots), ", ".join(os.path.basename(r) for r in roots[:10]) + ("…" if len(roots) > 10 else "")))
        g, cov, results = build_many(roots, args.out, jobs=args.jobs)
        if g is None:
            print("全部 no-op"); return
        print("[build] 合并图 节点=%d 边=%d 扫描文件=%d 重建仓=%d → %s" %
              (len(g.nodes), len(g.edges), cov["files_scanned"],
               sum(1 for _, st in results if st == "rebuild"), os.path.join(args.out, "graph.json")))
        return
    total_cov = {"files_scanned": 0, "skipped": []}
    for i, repo in enumerate(args.repos):
        name = os.path.basename(os.path.abspath(repo)) or ("repo%d" % i)
        out = args.out if (args.merge and len(args.repos) == 1) else os.path.join(args.out, name)
        g, cov = build(repo, out, os.path.join(HERE, "seeds.json"))
        total_cov["files_scanned"] += cov["files_scanned"]
        total_cov["skipped"] += cov["skipped"]
        print("[build] %-24s 节点=%-5d 边=%-5d 扫描文件=%d → %s" %
              (name, len(g.nodes), len(g.edges), cov["files_scanned"], os.path.join(out, "graph.json")))
        if cov["skipped"]:
            print("         覆盖缺口 %d 条（详见 coverage.json）" % len(cov["skipped"]))

def cmd_query(args):
    from domimap.graph import Graph
    from domimap.search import Searcher
    g = Graph.load(args.graph)
    from domimap.graph import load_seeds
    seeds = load_seeds(os.path.join(os.path.dirname(os.path.abspath(__file__)), "seeds.json"))
    s = Searcher(g, cache_path=args.graph + ".idx.json")
    from domimap.knowledge import attach_if_present
    attach_if_present(s, args.graph)  # 图旁 knowledge.db（人工/LLM 笔记）存在才挂
    r = s.query(args.text, top_k=args.top, domain=args.domain, seeds=seeds)
    if getattr(args, "json", False):
        import json as _j
        print(_j.dumps({"seeds": [{"id": n["id"], "kind": n["kind"], "name": n["name"],
                                   "file": n["file"]} for n in r["seeds"]],
                        "refused": r.get("refused", False)}, ensure_ascii=False))
    else:
        print(r["text"])
    if r.get("refused"):
        sys.exit(3)  # 退出码契约（graphify 范式）：3=无匹配

def cmd_domain(args):
    from domimap.graph import Graph
    g = Graph.load(args.graph)
    m = g.domain_map()
    for dom, a in sorted(m.items()):
        if dom == "__shared__":
            continue
        print("【%s】服务 %d: %s | 表 %d: %s | 主题: %s | 文档 %d" %
              (dom, len(a["services"]), ",".join(a["services"][:10]),
               len(a["tables"]), ",".join(a["tables"][:10]),
               ",".join(a["topics"][:5]) or "-", a["docs"]))
    sh = m.get("__shared__", {}).get("shared", [])
    for x in sh:
        print("⚠ 跨域共享表: %s ← %s（改动需多域评审）" % (x["table"], "+".join(x["domains"])))

def cmd_impact(args):
    from domimap.graph import Graph
    g = Graph.load(args.graph)
    start, deps = g.impact(args.symbol, args.depth)
    if not start:
        print("无匹配符号"); sys.exit(4)
    for n in start:
        print("起点: [%s] %s @%s" % (n["kind"], n["name"], n["file"]))
    for src, kind, dst in deps[:40]:
        print("  ← %s --%s(%s)--> %s" % (src["name"], kind, dst["name"], src["meta"].get("domain", "")))

def cmd_review(args):
    from domimap.graph import Graph
    g = Graph.load(args.graph)
    amb = [e for e in g.edges if e["conf"] == "AMBIGUOUS"]
    os.makedirs(args.out, exist_ok=True)
    p = os.path.join(args.out, "待审-AMBIGUOUS边.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write("# domimap 人审队列（AMBIGUOUS 边）\n\n> 审批后把结论写入 `reviewed/`，走双通道写回（claude-obsidian 审批范式）。\n\n")
        for e in amb:
            f.write("- [ ] `%s` --%s(%s)--> `%s`  prov=%s\n" %
                    (e["src"], e["kind"], e["conf"], e["dst"], e["prov"]))
    print("导出 %d 条待审边 → %s" % (len(amb), p))

def cmd_ui(args):
    """本地只读搜索/证据阅读页面（仅回环；与 CLI/MCP 同一 Searcher 语义）。"""
    from domimap.ui import serve_forever
    serve_forever(args.graph, args.host, args.port)

def cmd_serve(args):
    from domimap.mcp import serve
    serve(args.graph)

def cmd_read(args):
    """按证据 ID 读固化片段（源修改/删除后仍为旧版本，AC-R02-01 消费面）。"""
    from domimap.store import EvidenceStore
    import json as _json
    store = EvidenceStore(args.store)
    row = store.db.execute("SELECT sid FROM evidence WHERE ev_id=?", (args.ev_id,)).fetchone()
    if not row:
        print("无此证据 ID"); sys.exit(4)
    ev = store.evidence_for_source(row[0])
    print(_json.dumps({k: v for k, v in ev.items() if k != "text"}, ensure_ascii=False, indent=1))
    print("--- 片段 ---")
    print(ev["text"] if ev.get("available") else "（不可用：%s）" % ev.get("reason"))

def cmd_update(args):
    from domimap.batch import update
    g, cov, results = update(args.out)
    if g is None and not results:
        print("update: 该目录无 manifest（请先用 build --discover 建立工作区）"); sys.exit(5)
    for label, st in results:
        print("[update] %-28s %s" % (label, st))
    if g is not None:
        print("[update] 合并图 → %s  节点=%d 边=%d（重建仓 %d/%d）" %
              (os.path.join(args.out, "graph.json"), len(g.nodes), len(g.edges),
               sum(1 for _, st in results if st == "rebuild"), len(results)))
    else:
        print("[update] 全部 no-op（毫秒级校验，无变更）")

def cmd_scenario(args):
    from domimap.graph import Graph, load_seeds
    from domimap.search import Searcher
    from domimap import scenario
    g = Graph.load(args.graph)
    s = Searcher(g, cache_path=args.graph + ".idx.json")
    if args.kind == "req":
        seeds = load_seeds(os.path.join(os.path.dirname(os.path.abspath(__file__)), "seeds.json"))
        print(scenario.scenario_req(g, s, args.text, seeds))
    else:
        print(scenario.scenario_trb(g, s, args.text))

def cmd_enrich(args):
    """可选 LLM 语义增强：一条命令把图内 Doc 材料交给可配置模型生成草稿笔记（R05 草稿纪律）。"""
    from domimap.llm_enrich import enrich, LlmConfigError
    try:
        stats = enrich(args.graph, limit=args.limit, model=args.model, endpoint=args.endpoint,
                       max_tokens=args.max_tokens, cap=args.cap,
                       dry_run=args.dry_run, force=args.force)
    except LlmConfigError as error:
        print(str(error))
        sys.exit(6)  # 退出码契约：6=LLM 未配置（不静默降级）
    mode = "（dry-run，未联网未落库）" if stats["dry_run"] else ""
    print("[enrich] model=%s 选择=%d 新调用=%d 缓存命中=%d 新笔记=%d 解析失败=%d%s" % (
        stats["model"], stats["selected"], stats["called"], stats["cached"],
        stats["notes"], stats["errors"], mode))
    print("[enrich] 笔记已入 knowledge.db（inference 草稿）；检索时标注 conf=LLM。")


def main():
    ap = argparse.ArgumentParser(prog="domimap", description="多仓 Java 知识中台 MVP")
    ap.add_argument("-g", "--graph", default=os.path.join("out", "mini", "graph.json"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    def with_g(p):
        p.add_argument("-g", "--graph", default=ap.get_default("graph"))
        return p
    with_g(sub.add_parser("doctor")).set_defaults(fn=cmd_doctor)
    b = sub.add_parser("build"); b.add_argument("repos", nargs="+"); b.add_argument("-o", "--out", default="out")
    b.add_argument("--merge", action="store_true")
    b.add_argument("--discover", action="store_true", help="把参数视为工作区根目录，自动发现子仓并合并建图")
    b.add_argument("--jobs", type=int, default=8); b.set_defaults(fn=cmd_build)
    with_g(sub.add_parser("update")).add_argument("-o", "--out", default="out")
    sub.choices["update"].set_defaults(fn=cmd_update)
    sc = with_g(sub.add_parser("scenario")); sc.add_argument("kind", choices=["req", "trb"])
    sc.add_argument("text"); sc.set_defaults(fn=cmd_scenario)
    q = with_g(sub.add_parser("query")); q.add_argument("text"); q.add_argument("--top", type=int, default=6)
    q.add_argument("--json", action="store_true")
    q.add_argument("--domain"); q.set_defaults(fn=cmd_query)
    with_g(sub.add_parser("domain")).set_defaults(fn=cmd_domain)
    i = with_g(sub.add_parser("impact")); i.add_argument("symbol"); i.add_argument("--depth", type=int, default=2)
    i.set_defaults(fn=cmd_impact)
    r = with_g(sub.add_parser("review")); r.add_argument("-o", "--out", default="out/review"); r.set_defaults(fn=cmd_review)
    with_g(sub.add_parser("serve")).set_defaults(fn=cmd_serve)
    u = with_g(sub.add_parser("ui")); u.add_argument("--host", default="127.0.0.1")
    u.add_argument("--port", type=int, default=8765); u.set_defaults(fn=cmd_ui)
    rd = sub.add_parser("read"); rd.add_argument("ev_id")
    rd.add_argument("--store", default=os.path.join("out", "store.db")); rd.set_defaults(fn=cmd_read)
    en = with_g(sub.add_parser("enrich")); en.add_argument("--limit", type=int, default=5)
    en.add_argument("--dry-run", action="store_true"); en.add_argument("--force", action="store_true")
    en.add_argument("--model"); en.add_argument("--endpoint"); en.add_argument("--max-tokens", type=int)
    en.add_argument("--cap", type=int, default=8000,
                    help="单篇材料送入模型的字符上限（R08 资源纪律）")
    en.set_defaults(fn=cmd_enrich)
    args = ap.parse_args()
    args.fn(args)

if __name__ == "__main__":
    main()
