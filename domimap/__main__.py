#!/usr/bin/env python3
"""domimap CLI — 多仓 Java 知识中台（可执行 MVP）。

命令：
  doctor                     环境自检（平台/可选依赖/图谱状态）
  build <repo...> -o DIR     扫描仓库 → 统一图 graph.json + coverage.json
                             （--merge 单仓直出到 -o 目录；--discover 把参数视为工作区根，
                             自动发现子仓合并建图，并生成证据库 store.db 与增量清单）
  query TEXT --as-of DATE    历史范围查询（资格按该时刻判定；默认按当前时间排除过期/被替代资料）
  doc TEXT                   文档检索（与 MCP kg_doc_search 同参同观测）
  update -o DIR              工作区增量重建（manifest 未变时毫秒级 no-op）
  rebind LABEL PATH -o DIR   来源根移动后重绑物理路径（sid/节点 ID 不变，再 update）
  trust add|list|remove      可信上下文根登记（只有登记根的 AGENTS/SOUL 作为指令加载）
  context [--scope DIR]      查看当前生效的可信上下文与变更
  export-workspace WS DEST   整库导出（证据/代/图/来源登记/知识库；--include-queries 才带查询日志）
  restore-workspace ARCHIVE TARGET  整库恢复到新目录（校验失败不留半成品）
  query "文本" -g FILE        混合检索（词法种子+一跳图扩展；诚实拒答时退出码 3）
  domain -g FILE             领域地图（含跨域共享表）
  impact <符号> -g FILE      影响面（反向依赖）
  read <ev_id> --store DB    按证据 ID 读固化片段（源修改/删除后仍为旧版本）
  feedback <event_id> --relevance hit|partial|miss|not_applicable
                            提交/修订查询反馈（追加修订保留历史；--outcome 任务结果）
  history / qstats / qexport 查询记录分页列表 / 反馈统计（H/(H+P+M) 口径）/ 样例导出
  issues / diagnose         问题簇列表 / 规则预检诊断包（--ai 可选模型分析，--out 导出）
  replay / evolution        固定样本集回放（基线/候选/回滚比较）/ 闭环追溯与启用登记
  scenario req|trb "文本"    需求定位卡 / 问题排查卡
  review -g FILE -o DIR      AMBIGUOUS 边导出 Obsidian 待审页（人审双通道）
  enrich -g FILE [--limit N] 可选 LLM 语义增强：Doc 材料生成 inference 草稿笔记
                             （--dry-run/--force/--model/--endpoint；key 走 GLM_API_KEY 等
                             环境变量，未配置退出码 6；产物标注 conf=LLM 不混入事实）
  serve -g FILE              MCP stdio 服务器（7 个只读 kg_* 工具含 kg_context；--enable-write 加 kg_feedback）
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
    # LLM 语义增强层配置态（不打印 key 本体）
    try:
        from domimap import llm_enrich
        key_ok = bool(os.environ.get("GLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
                      or (os.environ.get("DOMIMAP_LLM_KEY_HELPER", "")
                          and os.path.isfile(os.path.expanduser(
                              os.environ["DOMIMAP_LLM_KEY_HELPER"]))))
        print("  [LLM] endpoint=%s model=%s key=%s" % (
            os.environ.get("DOMIMAP_LLM_ENDPOINT") or llm_enrich.DEFAULT_ENDPOINT,
            os.environ.get("DOMIMAP_LLM_MODEL") or llm_enrich.DEFAULT_MODEL,
            "已配置" if key_ok else "未配置（enrich 退出码 6）"))
        if g and os.path.exists(g):
            base = os.path.dirname(os.path.abspath(g))
            jsonl = os.path.join(base, "enrichment.jsonl")
            if os.path.exists(jsonl):
                entries = [json.loads(l) for l in open(jsonl, encoding="utf-8")
                           if l.strip().startswith("{")]
                ok = sum(1 for e in entries if e.get("status") == "ok")
                print("  [LLM] 审计 %s：%d 条（ok=%d，error=%d）" % (
                    "enrichment.jsonl", len(entries), ok, len(entries) - ok))
            kdb = os.path.join(base, "knowledge.db")
            if os.path.exists(kdb):
                from domimap.knowledge import KnowledgeStore, LLM_NOTE_PREFIX
                kb = KnowledgeStore(kdb)
                llm_notes = sum(1 for n in kb.list_active()
                                if n["body"].startswith(LLM_NOTE_PREFIX))
                kb.close()
                print("  [LLM] knowledge.db：LLM 草稿笔记 %d 条（active）" % llm_notes)
    except Exception:
        pass  # doctor 不因 LLM 段缺配置/缺文件而失败

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

def cmd_embed(args):
    """嵌入索引（product-embedding-index）：图旁 <graph>.emb.json，幂等，查询期 --embed 启用。"""
    from domimap.graph import Graph
    from domimap import embedding
    g = Graph.load(args.graph)
    path = embedding.store_path_for(args.graph)
    existing = embedding.load_store(path) or {}
    try:
        store, stats = embedding.build_index(g, targets=args.targets,
                                             limit=args.limit, existing=existing)
    except embedding.EmbeddingUnavailable as error:
        import sys
        print("嵌入后端不可用：%s" % error, file=sys.stderr)
        raise SystemExit(6)
    embedding.save_store(store, path)
    import json as _j
    if getattr(args, "json", False):
        print(_j.dumps({"store": path, **stats}, ensure_ascii=False))
    else:
        print("嵌入索引完成：%s（后端 %s，共 %d 项，新嵌 %d，复用 %d；查询用 --embed 启用语义融合）"
              % (path, stats["backend"], stats["total"], stats["embedded"], stats["reused"]))


def cmd_query(args):
    from domimap.service import AppService
    svc = AppService(args.graph)  # 与 MCP/UI 同一装配与默认参数（product#6）
    overrides = {"top_k": args.top, "domain": args.domain, "as_of": getattr(args, "as_of", None)}
    for flag in ("semantic", "rerank", "embed"):
        if getattr(args, flag, False):
            overrides[flag] = True
    if getattr(args, "rerank_pool", None):
        overrides["rerank_pool"] = args.rerank_pool
    from domimap.observation import observation_enabled
    from domimap.service import ServiceError
    try:
        r, obs = svc.query(args.text, "cli", **overrides)
    except ServiceError as e:
        print("query: %s" % e, file=sys.stderr); sys.exit(2)
    if getattr(args, "json", False):
        import json as _j
        print(_j.dumps({"seeds": [{"id": n["id"], "kind": n["kind"], "name": n["name"],
                                   "file": n["file"]} for n in r["seeds"]],
                        "refused": r.get("refused", False),
                        "query_id": obs.get("event_id"),
                        "recording": obs["status"]}, ensure_ascii=False))
    else:
        print(r["text"])
        if observation_enabled():  # 关闭记录时不留输出足迹；失败状态进 stderr 不碰 stdout 契约
            print("（观测：%s %s）" % (obs.get("event_id") or "-", obs["status"]),
                  file=sys.stderr)
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
    from domimap.service import AppService, ServiceError
    svc = AppService(args.graph)
    try:
        r = svc.impact(args.symbol, args.depth, args.max_nodes)
    except ServiceError as e:
        print(str(e)); sys.exit(4)
    for n in r["start"]:
        print("起点: [%s] %s @%s" % (n["kind"], n["name"], n["file"]))
    for src, kind, dst in r["deps"]:
        dom = src["meta"].get("domain", "")
        print("  ← %s --%s--> %s%s" % (src["name"], kind, dst["name"], ("  [%s]" % dom) if dom else ""))
    if r["partial"]:
        print("（partial：影响面在 %d 节点预算内截断，--max-nodes 可调）" % r["max_nodes"])


def cmd_doc(args):
    """文档检索（与 MCP kg_doc_search 同参同观测）。"""
    from domimap.service import AppService
    svc = AppService(args.graph)
    docs, r, obs = svc.doc_search(args.text, "cli", top_k=args.top)
    if not docs:
        print("文档无匹配（诚实拒答：不编造）。"); sys.exit(3)
    for d in docs:
        print("- %s @%s" % (d["name"], d["file"]))

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
    serve(args.graph, enable_write=args.enable_write)

def cmd_read(args):
    """按证据 ID 读固化片段（源修改/删除后仍为旧版本，AC-R02-01 消费面）。"""
    from domimap.store import EvidenceStore
    import json as _json
    store = EvidenceStore(args.store)
    try:
        ev = store.read_evidence(args.ev_id)
    finally:
        store.close()
    if ev is None:
        print("无此证据 ID"); sys.exit(4)
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

def cmd_rebind(args):
    """来源根移动后的显式重绑（AC-R01-02）：改物理路径，逻辑身份不变；随后 update 增量校验。"""
    from domimap.batch import rebind
    try:
        info = rebind(args.out, args.label, args.path)
    except KeyError as e:
        print("rebind: %s（工作区 %s 下无该 manifest）" % (e.args[0], args.out)); sys.exit(4)
    except FileNotFoundError as e:
        print("rebind: %s" % e); sys.exit(4)
    print("[rebind] %s: %s → %s（运行 `domimap update -o %s` 校验增量）" %
          (info["label"], info["old_root"], info["root"], args.out))

def cmd_export_workspace(args):
    """整库导出（R07）：证据库+blob+代+图+来源登记+知识库 → 可校验目录；查询日志默认不随包。"""
    from domimap.workspace import export_workspace
    try:
        m = export_workspace(args.workspace, args.dest, include_queries=args.include_queries)
    except (FileExistsError, FileNotFoundError) as e:
        print("export-workspace: %s" % e); sys.exit(4)
    print("[export] %s → %s  文件=%d 来源=%d 证据=%d 知识库=%s%s" % (
        args.workspace, args.dest, len(m["files"]), m["components"]["sources"], m["counts"]["evidence"],
        "是" if m["components"]["knowledge"] else "无",
        "  ⚠ 含查询日志，勿公开发布" if m.get("contains_query_log") else ""))


def cmd_restore_workspace(args):
    """整库恢复到不存在的目标目录：逐成员校验（路径/链接/sha）后原子发布；失败不留半成品。"""
    from domimap.workspace import restore_workspace
    try:
        r = restore_workspace(args.archive, args.target)
    except FileExistsError as e:
        print("restore-workspace: %s" % e); sys.exit(4)
    except ValueError as e:
        print("restore-workspace: 校验失败——%s" % e); sys.exit(5)
    print("[restore] %s → %s  文件=%d 节点=%d 证据=%d 知识=%s" % (
        args.archive, args.target, r["files"], r["nodes"], r["evidence"],
        ("%d 条笔记" % r["knowledge"]["notes"]) if r["knowledge"] else "无"))


def cmd_trust(args):
    """可信上下文根登记（F3）：只有这里登记的目录，其 AGENTS.md/SOUL.md 才会被当作指令加载。"""
    from domimap.store import EvidenceStore
    db = os.path.join(os.path.dirname(os.path.abspath(args.graph)), "store.db")
    if not os.path.exists(db):
        print("无证据库（先 build 工作区）：%s" % db); sys.exit(4)
    store = EvidenceStore(db)
    try:
        if args.action == "add":
            if not args.label or not args.path:
                print("用法：domimap trust add LABEL PATH -g 图"); sys.exit(2)
            try:
                rec = store.register_trusted_root(args.label, args.path)
            except (ValueError, FileNotFoundError) as e:
                print("trust add: %s" % e); sys.exit(4)
            from domimap.context import load_context
            out = load_context(rec["path"], trusted=[rec["path"]])
            print("[trust] 已登记 %s → %s（规则文件 %d：%s）" % (
                rec["label"], rec["path"], len(out["items"]),
                ", ".join(i["path"] for i in out["items"]) or "无"))
        elif args.action == "remove":
            if not args.label:
                print("用法：domimap trust remove LABEL -g 图"); sys.exit(2)
            ok = store.remove_trusted_root(args.label)
            print("[trust] 已移除 %s" % args.label if ok else "[trust] 未登记：%s" % args.label)
            if not ok:
                sys.exit(4)
        else:
            roots = store.trusted_roots()
            if not roots:
                print("[trust] 无登记的可信根（domimap trust add LABEL PATH -g 图）"); return
            from domimap.context import load_context
            for r in roots:
                try:
                    out = load_context(r["path"], trusted=[r["path"]])
                    files = ", ".join(i["path"] for i in out["items"]) or "无规则文件"
                except PermissionError as e:
                    files = "不可读：%s" % e
                print("[trust] %-16s %s  (%s)" % (r["label"], r["path"], files))
    finally:
        store.close()


def cmd_context(args):
    """查看当前生效的可信上下文（CLI 人工检索也能看到 F3 状态）。"""
    from domimap.service import AppService, ServiceError
    svc = AppService(args.graph)
    try:
        ctx = svc.trusted_context(scope=args.scope)
    except ServiceError as e:
        print("context: %s" % e); sys.exit(2)
    if ctx.get("note"):
        print(ctx["note"]); return
    print("[context] 可信根：%s  范围：%s" % (", ".join(r["label"] for r in ctx["roots"]), ctx["scope"] or "/"))
    for i in ctx["items"]:
        print("  %s %s/%s  sha256 %s  %dB" % ("*" if i.get("effective") else " ", i["root"], i["path"],
                                              i["sha256"][:12], i["size"]))
    if ctx["changed"]:
        print("  变更（自上次加载）：%s" % ", ".join(ctx["changed"]))
    if ctx["truncated"]:
        print("  预算超限，已丢弃：%s" % ", ".join(ctx["dropped"]))
    if ctx["text"]:
        print()
        print(ctx["text"])


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
    """可选 LLM 语义增强：一条命令把图内材料交给可配置模型生成草稿笔记（R05 草稿纪律）。"""
    import json as _j
    from domimap.llm_enrich import enrich, LlmBusyError, LlmConfigError
    try:
        stats = enrich(args.graph, limit=args.limit, targets=args.targets, model=args.model,
                       endpoint=args.endpoint, max_tokens=args.max_tokens, cap=args.cap,
                       dry_run=args.dry_run, force=args.force, keep_old=args.keep_old,
                       budget_tokens=args.budget_tokens, timeout=args.timeout)
    except LlmConfigError as error:
        print(str(error))
        sys.exit(6)  # 退出码契约：6=LLM 未配置/目录忙（不静默降级）
    except LlmBusyError as error:
        print(str(error))
        sys.exit(6)
    if getattr(args, "json", False):
        print(_j.dumps(stats, ensure_ascii=False, indent=1))
        return
    mode = "（dry-run，未联网未落库）" if stats["dry_run"] else ""
    stopped = "，%d 篇 skipped（原因=%s）" % (stats["skipped"], stats["stopped_reason"]) \
        if stats.get("stopped_reason") else ""
    print("[enrich] model=%s targets=%s 选择=%d 新调用=%d 缓存命中=%d 新笔记=%d 解析失败=%d%s%s" % (
        stats["model"], args.targets, stats["selected"], stats["called"], stats["cached"],
        stats["notes"], stats["errors"], stopped, mode))
    if "cost_estimate" in stats:
        c = stats["cost_estimate"]
        print("[enrich] 成本估算：%.6f（in %d / out %d tokens）" % (
            c["estimate"], c["input_tokens"], c["output_tokens"]))
    print("[enrich] 笔记已入 knowledge.db（inference 草稿）；检索时标注 conf=LLM。")


def cmd_schema(args):
    """机器可读图谱 schema（R11：AI 客户端不读源码即可理解节点/边/置信度语义）。"""
    import json as _json
    with open(os.path.join(HERE, "schema.json"), encoding="utf-8") as f:
        print(_json.dumps(_json.load(f), ensure_ascii=False, indent=1))


def _feedback_store(args):
    from domimap.feedback import FeedbackStore
    graph = args.graph
    if not os.path.exists(graph):
        print("图不存在：%s" % graph, file=sys.stderr); sys.exit(4)
    qdb = os.path.join(os.path.dirname(os.path.abspath(graph)), "queries.db")
    if not os.path.exists(qdb):
        print("无查询记录库（queries.db；先发起查询或开启观测）", file=sys.stderr); sys.exit(4)
    return FeedbackStore(qdb)


def cmd_feedback(args):
    """提交/修订查询反馈（hit/partial/miss + 任务结果；追加修订保留历史）。"""
    import json as _j
    store = _feedback_store(args)
    try:
        from domimap.feedback import FeedbackError
        try:
            r = store.submit(args.event_id, args.relevance,
                             task_outcome=args.outcome or "unknown",
                             source=args.source, reason=args.reason,
                             expected_evidence=args.expected,
                             idempotency_key=args.key,
                             expected_revision=args.expected_revision)
        except FeedbackError as e:
            print(str(e)); sys.exit(4)
    finally:
        store.close()
    print(_j.dumps(r, ensure_ascii=False))


def cmd_history(args):
    """查询记录分页列表（按入口/状态/拒答原因/触发类型过滤；含有效反馈）。"""
    import json as _j
    store = _feedback_store(args)
    try:
        r = store.list_events(entry=args.entry, status=args.status,
                              refusal_reason=args.refusal_reason, trigger=args.trigger,
                              limit=args.limit, offset=args.offset)
    finally:
        store.close()
    if getattr(args, "json", False):
        print(_j.dumps(r, ensure_ascii=False, indent=1))
        return
    print("共 %d 条（显示 %d-%d）" % (r["total"], r["offset"] + 1,
                                    r["offset"] + len(r["items"])))
    for it in r["items"]:
        fb = it["feedback_relevance"] or ("disputed" if it["disputed"] else "-")
        print("%s  [%s/%s] %s%s  fb=%s  %s" % (
            it["event_id"], it["entry"], it["trigger_kind"], it["status"],
            ("/" + it["refusal_reason"]) if it["refusal_reason"] else "",
            fb, it["query_digest"]))


def cmd_qstats(args):
    """反馈统计：完整命中率 H/(H+P+M)、判定覆盖率、来源分列、正确拒答比例。"""
    import json as _j
    store = _feedback_store(args)
    try:
        r = store.stats()
    finally:
        store.close()
    if getattr(args, "json", False):
        print(_j.dumps(r, ensure_ascii=False, indent=1))
        return
    e = r["effective"]
    print("事件 %d（profile %d，重复 %d）｜触发 user %d / 非 user %d" % (
        r["events"], r["profiles"]["distinct"], r["profiles"]["repeated_events"],
        r["trigger"]["user"], r["trigger"]["non_user"]))
    print("有效相关性 hit=%d partial=%d miss=%d unknown=%d n.a.=%d disputed=%d" % (
        e["hit"], e["partial"], e["miss"], e["unknown"], e["not_applicable"],
        e["disputed"]))
    print("已判定完整命中率 H/(H+P+M) = %s（分母 %d，partial 单列不折算）" % (
        r["hit_rate"] if r["hit_rate"] is not None else "无判定样本",
        r["hit_rate_denominator"]))
    print("判定覆盖率 %s｜未反馈比例 %s" % (r["judgment_coverage"],
                                          r["unfeedbacked_ratio"]))
    print("正确拒答：%d/%d（refused 且有权威反馈者）" % (
        r["correct_refusal"]["correct_abstention"],
        r["correct_refusal"]["refused_with_feedback"]))
    for src, c in sorted(r["by_source"].items()):
        print("  来源 %-16s 最新修订 %d（hit=%s partial=%s miss=%s）" % (
            src, c["latest_count"], c.get("hit", 0), c.get("partial", 0),
            c.get("miss", 0)))


def cmd_issues(args):
    """问题簇列表（miss/失败/异常按查询摘要归并；正确拒答不入队）。"""
    import json as _j
    from domimap.diagnosis import list_issues
    issues = list_issues(args.graph)
    if getattr(args, "json", False):
        print(_j.dumps(issues, ensure_ascii=False, indent=1))
        return
    if not issues:
        print("无待诊断问题簇（正确拒答不入队；先在查询后提交 miss 反馈）")
        return
    for it in issues:
        dg = it["last_diagnosis"]
        print("%s  事件×%d  %s  %s" % (
            it["cluster_id"], it["event_count"], it["status"],
            ("诊断 " + dg["diagnosis_id"] + " ai=" + str(dg["ai_status"])) if dg else "未诊断"))


def cmd_diagnose(args):
    """规则预检 + 可选模型分析，输出结构化诊断包（不改检索行为）。"""
    import json as _j
    from domimap.graph import Graph
    from domimap.search import Searcher
    from domimap.diagnosis import diagnose
    from domimap.knowledge import attach_if_present
    g = Graph.load(args.graph)
    s = Searcher(g, cache_path=args.graph + ".idx.json")
    attach_if_present(s, args.graph)
    r = diagnose(args.graph, s, event_id=args.event, cluster_id=args.cluster,
                 query_text=args.query, use_ai=args.ai, entry="cli")
    if r.get("status") in ("empty", "unknown_event"):
        print("无可诊断对象：%s" % r["status"]); sys.exit(4)
    pack = r["pack"]
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            _j.dump(pack, f, ensure_ascii=False, indent=1)
    if getattr(args, "json", False):
        print(_j.dumps({"diagnosis_id": r["diagnosis_id"], "status": r["status"],
                        "ai_status": r["ai_status"], "pack": pack}, ensure_ascii=False,
                       indent=1))
        return
    print("诊断 %s（%s，ai=%s）%s" % (r["diagnosis_id"], r["status"], r["ai_status"],
                                    ("→ " + args.out) if args.out else ""))
    for f in pack["findings"]:
        print("  检查 %-20s %s" % (f["check"], f["result"]))
    for h in pack["hypotheses"]:
        print("  假设 %-24s %s" % (h["cause"], h["status"]))
        print("        %s" % h["support"])
    for u in pack["unknowns"]:
        print("  未知：%s" % u)


def cmd_evolution(args):
    """闭环追溯视图 / 改进启用登记：簇→事件→反馈→诊断→回放→决定。"""
    import json as _j
    from domimap import replay
    from domimap.diagnosis import list_issues
    if args.record_improvement:
        if not (args.cluster and args.baseline and args.candidate):
            print("--record-improvement 需要 --cluster/--baseline/--candidate",
                  file=sys.stderr)
            sys.exit(2)
        try:
            import importlib.util as _ilu
            _spec = _ilu.spec_from_file_location(
                "check_specs", os.path.join(os.path.dirname(HERE), "scripts",
                                            "check_specs.py"))
            _cs = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_cs)
            fp = _cs.source_fingerprint()
        except Exception:
            fp = None
        try:
            r = replay.record_improvement(
                args.graph, args.cluster, args.baseline, args.candidate,
                args.record_improvement, diagnosis_id=args.diagnosis,
                rollback_run=args.rollback, notes=args.notes,
                source_fingerprint=fp)
        except ValueError as e:
            print(str(e)); sys.exit(4)
        print(_j.dumps(r, ensure_ascii=False))
        return
    if args.cluster:
        c = replay.chain(args.graph, args.cluster)
        if getattr(args, "json", False):
            print(_j.dumps(c, ensure_ascii=False, indent=1))
            return
        if not c["cluster"]:
            print("无此问题簇：%s" % args.cluster); sys.exit(4)
        print("簇 %s（%s，事件×%d）" % (c["cluster"]["cluster_id"],
                                        c["cluster"]["status"],
                                        c["cluster"]["event_count"]))
        for e in c["events"]:
            print("  事件 %s [%s/%s] %s%s" % (e["event_id"], e["entry"],
                                              e["trigger_kind"], e["status"],
                                              ("/" + e["refusal_reason"])
                                              if e["refusal_reason"] else ""))
        for dg in c["diagnoses"]:
            print("  诊断 %s ai=%s" % (dg["diagnosis_id"], dg["ai_status"]))
            for f in dg["findings"]:
                print("    检查 %s → %s" % (f["check"], f["result"]))
        for r in c["replay_runs"]:
            print("  回放 %s [%s] %d/%d%s" % (r["run_id"], r["label"],
                                              r["summary"]["ok"],
                                              r["summary"]["total"],
                                              (" " + r["notes"]) if r["notes"] else ""))
        for im in c["improvements"]:
            print("  决定 %s %s（candidate=%s%s）" % (
                im["improvement_id"], im["decision"], im["candidate_run"],
                ("，rollback=" + im["rollback_run"]) if im["rollback_run"] else ""))
        return
    issues = list_issues(args.graph)
    if getattr(args, "json", False):
        print(_j.dumps(issues, ensure_ascii=False, indent=1))
        return
    if not issues:
        print("无问题簇积压（积压=未诊断优先，按影响面排序）")
        return
    for it in issues:
        dg = it["last_diagnosis"]
        print("%s  事件×%-3d %s  %s" % (
            it["cluster_id"], it["event_count"], it["status"],
            ("诊断 " + dg["diagnosis_id"] + " ai=" + str(dg["ai_status"]))
            if dg else "未诊断"))


def cmd_replay(args):
    """固定样本集回放（冻结摘要；trigger=replay 不污染用户统计；可对比基线 run）。"""
    import json as _j
    from domimap.graph import Graph
    from domimap.search import Searcher
    from domimap import replay
    from domimap.knowledge import attach_if_present
    try:  # 指纹可选（新克隆/缺 scripts 时回放仍可跑，仅记录为空）
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location(
            "check_specs", os.path.join(os.path.dirname(HERE), "scripts",
                                        "check_specs.py"))
        _cs = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_cs)
        fp = _cs.source_fingerprint()
    except Exception:
        fp = None
    samples, sha = replay.load_samples(args.samples)
    g = Graph.load(args.graph)
    s = Searcher(g, cache_path=args.graph + ".idx.json")
    attach_if_present(s, args.graph)
    run = replay.run_replay(args.graph, s, samples, sha, args.label,
                            notes=args.notes, source_fingerprint=fp,
                            cluster_id=args.cluster)
    out = {"run_id": run["run_id"], "label": args.label,
           "samples_sha256": sha, "summary": run["summary"]}
    if args.baseline:
        base = replay.get_run(args.graph, args.baseline)
        if base is None:
            print("基线 run 不存在：%s" % args.baseline); sys.exit(4)
        try:
            cmp_ = replay.compare_runs(base, run)
        except ValueError as e:
            print(str(e)); sys.exit(4)
        out["comparison"] = cmp_
        out["baseline_run_id"] = args.baseline
    if getattr(args, "json", False):
        print(_j.dumps(out, ensure_ascii=False, indent=1))
        return
    print("回放 %s（%s）：%d/%d 通过" % (run["run_id"], args.label,
                                        run["summary"]["ok"], run["summary"]["total"]))
    for x in run["results"]:
        print("  %-16s %s rank=%s top_k=%d%s" % (
            x["id"], "PASS" if x["ok"] else "MISS",
            x["rank"] if x["rank"] is not None else ("拒答" if x["refused"] else "无"),
            x["top_k"], ""))
    if "comparison" in out:
        c = out["comparison"]
        print("对比 %s：改善 %d、回归 %d、不变 %d（verdict=%s）" % (
            args.baseline, len(c["improvements"]), len(c["regressions"]),
            c["unchanged"], c["verdict"]))


def cmd_qsnapshot(args):
    """查询/反馈库一致性快照（SQLite backup API）。"""
    import json as _j
    store = _feedback_store(args)
    try:
        r = store.snapshot(args.out)
    finally:
        store.close()
    print(_j.dumps(r, ensure_ascii=False))


def cmd_qrestore(args):
    """安全恢复：先在备份上完整校验（schema/完整性/关联），失败绝不触碰原库；
    被其他连接占用时拒绝在线原地恢复。"""
    import json as _j
    from domimap.feedback import FeedbackError
    store = _feedback_store(args)
    try:
        r = store.restore(args.backup)
    except FeedbackError as e:
        print(str(e)); sys.exit(4)
    finally:
        try:
            store.close()
        except Exception:
            pass
    print(_j.dumps(r, ensure_ascii=False))


def cmd_qdelete(args):
    """受控删除查询事件（同步清理派生；改进固定证据拒绝；--all 须先出示快照）。"""
    import json as _j
    from domimap.feedback import FeedbackError
    store = _feedback_store(args)
    try:
        ids = args.ids or None
        r = store.delete_events(ids=ids, before=args.before,
                                delete_all=args.all, backup_path=args.backup)
    except FeedbackError as e:
        print(str(e)); sys.exit(4)
    finally:
        store.close()
    print(_j.dumps(r, ensure_ascii=False))


def cmd_qexport(args):
    """导出成功/失败开发样例（去重；未保存原文者 replayable=false）。"""
    import json as _j
    store = _feedback_store(args)
    try:
        samples = store.export_samples(args.kind)
    finally:
        store.close()
    out = {"kind": args.kind, "count": len(samples),
           "replayable": sum(1 for s in samples if s["replayable"]),
           "samples": samples}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        _j.dump(out, f, ensure_ascii=False, indent=1)
    print("导出 %d 个%s样例（可回放 %d）→ %s" % (out["count"], args.kind,
                                                out["replayable"], args.out))


def main():
    ap = argparse.ArgumentParser(prog="domimap", description="多仓 Java 知识中台 MVP")
    ap.add_argument("-g", "--graph", default=os.path.join("out", "mini", "graph.json"))
    ap.add_argument("--version", action="version", version="domimap " + __version__)
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
    q.add_argument("--as-of", dest="as_of", default=None,
                   help="历史范围查询：YYYY-MM-DD 或 epoch 秒；资格按该时刻判定（F4）")
    q.add_argument("--semantic", action="store_true",
                   help="低覆盖率回退启用 LLM 语义桥（需 GLM_API_KEY 等；默认关）")
    q.add_argument("--rerank", action="store_true",
                   help="BM25 top-N 候选 LLM 语义重排（需 GLM_API_KEY 等；默认关）")
    q.add_argument("--rerank-pool", type=int, default=None,
                   help="重排池大小（默认 50，上限 100）")
    q.add_argument("--embed", action="store_true",
                   help="启用嵌入语义融合（需先 domimap embed 建索引；默认关）")
    q.add_argument("--json", action="store_true")
    q.add_argument("--domain"); q.set_defaults(fn=cmd_query)
    with_g(sub.add_parser("domain")).set_defaults(fn=cmd_domain)
    i = with_g(sub.add_parser("impact")); i.add_argument("symbol"); i.add_argument("--depth", type=int, default=2)
    i.add_argument("--max-nodes", type=int, default=200, help="遍历预算（达到即停，结果标 partial）")
    i.set_defaults(fn=cmd_impact)
    dc = with_g(sub.add_parser("doc", help="文档检索（与 MCP kg_doc_search 同参）")); dc.add_argument("text")
    dc.add_argument("--top", type=int, default=None); dc.set_defaults(fn=cmd_doc)
    r = with_g(sub.add_parser("review")); r.add_argument("-o", "--out", default="out/review"); r.set_defaults(fn=cmd_review)
    ex = sub.add_parser("export-workspace", help="整库导出为可校验目录（证据/代/图/来源登记/知识库）")
    ex.add_argument("workspace", help="含 graph.json 的工作区目录"); ex.add_argument("dest")
    ex.add_argument("--include-queries", action="store_true", help="同时导出 queries.db（含查询日志，勿公开）")
    ex.set_defaults(fn=cmd_export_workspace)
    rs = sub.add_parser("restore-workspace", help="整库恢复到不存在的目标目录（逐成员校验，失败不留半成品）")
    rs.add_argument("archive"); rs.add_argument("target")
    rs.set_defaults(fn=cmd_restore_workspace)
    tr = with_g(sub.add_parser("trust", help="可信上下文根：add LABEL PATH | list | remove LABEL"))
    tr.add_argument("action", choices=["add", "list", "remove"]); tr.add_argument("label", nargs="?")
    tr.add_argument("path", nargs="?"); tr.set_defaults(fn=cmd_trust)
    cx = with_g(sub.add_parser("context", help="查看当前生效的 AGENTS.md/SOUL.md 可信上下文"))
    cx.add_argument("--scope", default=None, help="任务所在根内相对目录（嵌套规则取最具体一层）")
    cx.set_defaults(fn=cmd_context)
    rb = sub.add_parser("rebind", help="来源根移动后重绑物理路径（逻辑身份不变）")
    rb.add_argument("label"); rb.add_argument("path"); rb.add_argument("-o", "--out", default="out")
    rb.set_defaults(fn=cmd_rebind)
    sv = with_g(sub.add_parser("serve"))
    sv.add_argument("--enable-write", action="store_true",
                    help="启用写工具 kg_feedback（默认只读；经 MCP 转达的判定以 agent_relay 非权威来源记录）")
    sv.set_defaults(fn=cmd_serve)
    u = with_g(sub.add_parser("ui")); u.add_argument("--host", default="127.0.0.1")
    u.add_argument("--port", type=int, default=8765); u.set_defaults(fn=cmd_ui)
    rd = sub.add_parser("read"); rd.add_argument("ev_id")
    rd.add_argument("--store", default=os.path.join("out", "store.db")); rd.set_defaults(fn=cmd_read)
    sub.add_parser("schema").set_defaults(fn=cmd_schema)
    fb = with_g(sub.add_parser("feedback")); fb.add_argument("event_id")
    fb.add_argument("--relevance", required=True,
                    choices=["hit", "partial", "miss", "not_applicable", "unknown"])
    fb.add_argument("--outcome", choices=["success", "failure", "correct_abstention",
                                          "needs_clarification", "unknown"])
    fb.add_argument("--source", default="user_feedback",
                    choices=["user_feedback", "human_annotation", "dev_gold",
                             "rule_check", "ai_suggestion"])
    fb.add_argument("--reason"); fb.add_argument("--expected")
    fb.add_argument("--key", help="幂等键（同键同内容去重）")
    fb.add_argument("--expected-revision", dest="expected_revision", type=int,
                    help="同来源修订需携带其当前最新修订号（乐观并发）")
    fb.set_defaults(fn=cmd_feedback)
    hi = with_g(sub.add_parser("history"))
    hi.add_argument("--entry", choices=["cli", "mcp", "ui"])
    hi.add_argument("--status", choices=["ok", "refused", "error", "cancelled"])
    hi.add_argument("--refusal-reason", dest="refusal_reason")
    hi.add_argument("--trigger", choices=["user", "retry", "replay", "diagnostic"])
    hi.add_argument("--limit", type=int, default=20); hi.add_argument("--offset", type=int, default=0)
    hi.add_argument("--json", action="store_true"); hi.set_defaults(fn=cmd_history)
    qs = with_g(sub.add_parser("qstats")); qs.add_argument("--json", action="store_true")
    qs.set_defaults(fn=cmd_qstats)
    iss = with_g(sub.add_parser("issues")); iss.add_argument("--json", action="store_true")
    iss.set_defaults(fn=cmd_issues)
    dg = with_g(sub.add_parser("diagnose"))
    dg.add_argument("--event"); dg.add_argument("--cluster"); dg.add_argument("--query")
    dg.add_argument("--ai", action="store_true",
                    help="可选模型根因分析（每簇一次；无 key 时 ai=unavailable 不阻塞）")
    dg.add_argument("--out", help="诊断包 JSON 输出路径（建议 out/ 下）")
    dg.add_argument("--json", action="store_true"); dg.set_defaults(fn=cmd_diagnose)
    rp = with_g(sub.add_parser("replay")); rp.add_argument("--samples", required=True,
                                                           help="冻结样本集 JSON 文件")
    rp.add_argument("--cluster", help="关联问题簇（追溯链限定）")
    rp.add_argument("--label", default="candidate",
                    help="baseline | candidate | rollback | 自定义")
    rp.add_argument("--baseline", help="对比的基线 run_id（样本集摘要须一致）")
    rp.add_argument("--notes"); rp.add_argument("--json", action="store_true")
    rp.set_defaults(fn=cmd_replay)
    ev = with_g(sub.add_parser("evolution")); ev.add_argument("--cluster")
    ev.add_argument("--record-improvement", dest="record_improvement",
                    choices=["activated", "rejected", "rolled_back"])
    ev.add_argument("--baseline"); ev.add_argument("--candidate")
    ev.add_argument("--rollback"); ev.add_argument("--diagnosis")
    ev.add_argument("--notes"); ev.add_argument("--json", action="store_true")
    ev.set_defaults(fn=cmd_evolution)
    qe = with_g(sub.add_parser("qexport")); qe.add_argument("--kind", required=True,
                                                            choices=["success", "failure"])
    qe.add_argument("-o", "--out", default=os.path.join("out", "samples.json"))
    qe.set_defaults(fn=cmd_qexport)
    qs = with_g(sub.add_parser("qsnapshot")); qs.add_argument("-o", "--out", required=True)
    qs.set_defaults(fn=cmd_qsnapshot)
    qr = with_g(sub.add_parser("qrestore")); qr.add_argument("--backup", required=True)
    qr.set_defaults(fn=cmd_qrestore)
    qd = with_g(sub.add_parser("qdelete")); qd.add_argument("ids", nargs="*")
    qd.add_argument("--before", type=float); qd.add_argument("--all", action="store_true")
    qd.add_argument("--backup", help="--all 必须出示 qsnapshot 产出的备份路径")
    qd.set_defaults(fn=cmd_qdelete)
    en = with_g(sub.add_parser("enrich")); en.add_argument("--limit", type=int, default=5)
    en.add_argument("--targets", choices=["docs", "domain", "all"], default="docs")
    en.add_argument("--dry-run", action="store_true"); en.add_argument("--force", action="store_true")
    en.add_argument("--keep-old", action="store_true",
                    help="supersede 关闭：文档更新后旧 LLM 笔记不自动撤回")
    en.add_argument("--model"); en.add_argument("--endpoint"); en.add_argument("--max-tokens", type=int)
    en.add_argument("--timeout", type=float, help="单次调用超时秒数（默认 DOMIMAP_LLM_TIMEOUT 或 120）")
    en.add_argument("--budget-tokens", type=int,
                    help="本次运行 in+out token 预算，超限即停（剩余记 skipped）")
    en.add_argument("--cap", type=int, default=8000,
                    help="单篇材料送入模型的字符上限（R08 资源纪律）")
    en.add_argument("--json", action="store_true", help="机器可读输出（含逐篇明细）")
    en.set_defaults(fn=cmd_enrich)
    em = with_g(sub.add_parser("embed")); em.add_argument("--targets",
                                                          choices=["docs", "sql", "all"],
                                                          default="all")
    em.add_argument("--limit", type=int, default=None, help="只嵌前 N 个目标节点（试跑）")
    em.add_argument("--json", action="store_true", help="机器可读输出")
    em.set_defaults(fn=cmd_embed)
    args = ap.parse_args()
    args.fn(args)

if __name__ == "__main__":
    main()
