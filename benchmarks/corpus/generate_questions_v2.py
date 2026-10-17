#!/usr/bin/env python3
"""dev 题集 v2 生成器：修正语义（对照 specs/tasks/comparison-dev-questions-v2.md）。

与旧版（generate_questions.py）的根本差别：
- 文档理解题查询词来自**正文**（限制/例外/前提句），排除标题与文件名词。
- 时效题只用**文档内**日期/版本陈述；全程不调用 os.path.getmtime。
- 定位题标识符串查 ≤40%，其余用类/方法邻近中文注释关键词（内容→位置）。
- 旧式标题/README 检索题单列为 locator_diagnostic（诊断，不入四类）。
- 负例四因（无证据/近名/歧义/错范围），逐条带验证方法。
- questions（id/category/query）与 gold（family/paths/facts/disposition/verify）分文件。

输出：out/benchmark/dev-questions-v2.json 与 dev-gold-v2.json（out/ 不入库）。
"""
import json
import os
import re
import sys
import time
import zipfile

WS = os.path.expanduser("~/work/dev-corpus")
EXTRA = [os.path.expanduser(p) for p in (
    "EXTERNAL_FAMILY_PATH",
    "EXTERNAL_FAMILY_PATH",
    "EXTERNAL_FAMILY_PATH",
    "EXTERNAL_FAMILY_PATH")]
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTDIR = os.path.join(ROOT, "out", "benchmark")
SKIP = {".git", "node_modules", "target", "build", "__pycache__", ".idea"}

QUOTA = {"code_location": 30, "cross_repo_trace": 30, "document_reasoning": 30,
         "knowledge_freshness": 30, "locator_diagnostic": 20, "negative": 40}

CN = re.compile(r"[\u4e00-\u9fff]{2,}")
DATE = re.compile(r"(20\d{2})\s*[年./-]\s*(\d{1,2})\s*[月./-]?\s*(\d{1,2})\s*[日]?")
VERSION = re.compile(r"[vV]?(?<![\w.])(\d+\.\d+(?:\.\d+)?)(?![\w.])")
FRESH_KW = ("生效", "失效", "替代", "废弃", "更新于", "版本", "发布", "上线")
RESTRICT_KW = ("限制", "注意", "例外", "必须", "不支持", "前提", "回滚", "禁止",
               "风险", "条件", "默认不")
# mock/占位文本启发式（第 5 步诊断实证：sy_html 等 demo 页的"谁谁谁/啥啥啥"曾被当主题词）
PLACEHOLDER_TOKENS = {"谁谁谁", "啥啥啥", "某某某", "xxx", "xxxx", "xxxxx", "test",
                      "demo", "示例", "样例", "mock", "aaaa", "abc", "abcd"}
_PLACEHOLDER_RE = re.compile(r"^(.)\1{2,}$")
MOCK_MAX = 0.02  # 占位 token 占比超过此值的文档不参与成题（gold 质量下限）


def mock_ratio(doc):
    toks = doc["tokens"]
    if not toks:
        return 1.0
    ph = sum(1 for t in toks
             if t.lower() in PLACEHOLDER_TOKENS or _PLACEHOLDER_RE.match(t))
    return ph / len(toks)


def fam_root(name):
    for p in EXTRA:
        if os.path.basename(os.path.normpath(p)) == name:
            return p
    return os.path.join(WS, name)


def read_text(path, cap=200000):
    """utf-8 严格读取失败（dev-corp 中文文档多为 GB18030）则回退 GB18030——乱码会让
    中文正则全部失效，此前导致文档/时效题配额几乎为零。"""
    try:
        with open(path, encoding="utf-8") as stream:
            return stream.read(cap)
    except UnicodeDecodeError:
        try:
            with open(path, encoding="gb18030", errors="replace") as stream:
                return stream.read(cap)
        except OSError:
            return ""
    except OSError:
        return ""


def extract_document(path):
    """.docx/.html 机械文本抽取（stdlib zip + 去标签，grep 级、不经产品管线）。
    dev-corp 语料的知识主要在 docx/html（纯文本 .md/.txt 仅 2 个）；返回 (text, title) 或 None。"""
    low = path.lower()
    try:
        if low.endswith((".html", ".htm")):
            raw = read_text(path, 400000)
            raw = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw)
            tm = re.search(r"(?is)<title>(.{2,80}?)</title>", raw)
            title = re.sub(r"\s+", " ", tm.group(1)).strip() if tm else ""
            text = re.sub(r"(?s)<[^>]+>", " ", raw)
            return re.sub(r"[ \t\r\f\v]+", " ", text), title
        if low.endswith(".docx"):
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml").decode("utf-8", "replace")
            xml = re.sub(r"(?i)</w:p>", "\n", xml)
            text = re.sub(r"(?s)<[^>]+>", "", xml)
            lines = [ln.strip() for ln in text.split("\n") if len(ln.strip()) >= 4]
            title = lines[0][:60] if lines else ""
            return text, title
    except (OSError, zipfile.BadZipFile, KeyError):
        return None
    return None


def scan_family(root):
    """grep 级事实抽取（无产品依赖、无 mtime）。"""
    tables, classes, docs, locators = {}, [], [], []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP]
        for fn in filenames:
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, root).replace("\\", "/")
            low = fn.lower()
            if low.endswith((".xml",)) and ("mapper" in low or "sqlmap" in dirpath):
                text = read_text(path)
                for t in set(re.findall(
                        r"(?:FROM|JOIN|INTO|UPDATE)\s+`?([A-Za-z_][\w]{3,40})`?",
                        text, re.I)):
                    if not t.upper().startswith(("SELECT", "WHERE", "SET", "VALUES", "DUAL")):
                        line = text[:text.upper().find(t.upper())].count("\n") + 1
                        tables.setdefault(t, []).append((rel, line))
            elif low.endswith(".sql"):
                text = read_text(path)
                for m in re.finditer(
                        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?([A-Za-z_][\w]{3,40})`?",
                        text, re.I):
                    line = text[:m.start()].count("\n") + 1
                    tables.setdefault(m.group(1), []).append((rel, line))
            elif low.endswith(".java"):
                text = read_text(path)
                # 两遍法：先定位 class/interface 行，再取其前 6 行内的中文注释
                # （单一大正则的 /\*.*?\*/ 回溯在 200KB 文件上是 O(n²)，实测不可用）
                lines = text.split("\n")
                for i, line in enumerate(lines):
                    m = re.match(r"\s*public\s+(?:abstract\s+)?(?:class|interface)\s+"
                                 r"([A-Z]\w{4,40})\b", line)
                    if not m:
                        continue
                    head = "\n".join(lines[max(0, i - 6):i])
                    if "/*" in head or "//" in head:
                        comments = " ".join(CN.findall(head))
                    else:
                        comments = ""
                    classes.append((m.group(1), rel, comments))
            text, title = None, ""
            if low.endswith((".md", ".txt")) and os.path.getsize(path) < 200000:
                text = read_text(path)
                title_m = re.search(r"^#{1,3}\s+(.{4,60})$", text, re.M)
                title = title_m.group(1).strip() if title_m else ""
            elif low.endswith((".docx", ".html", ".htm")) and os.path.getsize(path) < 4000000:
                extracted = extract_document(path)
                if extracted:
                    text, title = extracted
            if text is not None and len(text) >= 400:
                sentences = [s.strip() for s in re.split(r"[。\n]", text)
                             if 12 <= len(s.strip()) <= 160
                             and any(k in s for k in RESTRICT_KW + FRESH_KW)]
                dates = [(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))
                         for m in DATE.finditer(text)]
                body_tokens = CN.findall(text)
                doc_entry = {"rel": rel, "title": title, "sentences": sentences,
                             "dates": dates, "tokens": body_tokens,
                             "stem": os.path.splitext(fn)[0]}
                doc_entry["mock_ratio"] = round(mock_ratio(doc_entry), 4)
                docs.append(doc_entry)
                if title and doc_entry["mock_ratio"] <= MOCK_MAX:
                    locators.append((title, rel))
            if low.startswith("readme") and low.endswith((".md", ".txt")):
                locators.append((os.path.splitext(fn)[0], rel))
    classes.sort(key=lambda x: (x[1], x[0]))
    docs.sort(key=lambda d: d["rel"])
    locators.sort()
    return {"tables": {k: sorted(v) for k, v in sorted(tables.items())},
            "classes": classes, "docs": docs, "locators": locators}


def topic_words(doc):
    """正文中高频中文词，排除出现于标题/文件名的词与占位 token——保证查询
    不退化成标题检索，也不被 mock 页占位文本污染。"""
    banned = doc["title"] + doc["stem"]
    counts = {}
    for token in doc["tokens"]:
        if len(token) < 2 or token in banned:
            continue
        if token.lower() in PLACEHOLDER_TOKENS or _PLACEHOLDER_RE.match(token):
            continue
        counts[token] = counts.get(token, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]


def build(families, root_of=None):
    root_of = root_of or fam_root
    facts = {f: scan_family(root_of(f)) for f in families}
    by_table = {}
    for f, d in facts.items():
        for t in d["tables"]:
            by_table.setdefault(t, []).append(f)
    questions, gold = [], []

    def add(category, query, families_, paths, facts_, disposition, verify):
        qid = "dv2-%04d" % len(questions)
        questions.append({"id": qid, "category": category, "query": query})
        gold.append({"id": qid, "category": category, "families": families_,
                     "gold_paths": paths, "necessary_facts": facts_,
                     "disposition": disposition, "verify_method": verify})
        return qid

    # 1) code_location：≤40% 标识符题；≥60% 注释关键词题（内容→位置）
    ident, comment_q = 0, []
    for f in sorted(facts):
        d = facts[f]
        for t, hits in list(d["tables"].items())[:2]:
            if ident < QUOTA["code_location"] * 0.4:
                rel, line = hits[0]
                add("code_location", "%s 表 定义 写入 位置" % t, [f],
                    ["%s/%s" % (f, rel)], ["%s:%d 定义/引用表 %s" % (rel, line, t)],
                    "answer", "grep Mapper/DDL")
                ident += 1
        for name, rel, comments in d["classes"]:
            if comments and len(CN.findall(comments)) >= 2:
                comment_q.append((f, name, rel, comments))
    for f, name, rel, comments in comment_q:  # 注释关键词成题（不出现类名，防标识符串查）
        if len([q for q in questions if q["category"] == "code_location"]) >= QUOTA["code_location"]:
            break
        words = CN.findall(comments)[:4]
        if len(words) < 2:
            continue
        add("code_location", " ".join(words) + " 处理类 位置", [f],
            ["%s/%s" % (f, rel)], ["%s 含注释「%s」的类 %s" % (rel, comments[:40], name)],
            "answer", "注释邻近类声明（内容→位置）")

    # 2) cross_repo_trace：同名表 ≥2 族
    cross = 0
    for t in sorted(by_table):
        fams = sorted(set(by_table[t]))
        if len(fams) >= 2 and cross < QUOTA["cross_repo_trace"]:
            paths, fs = [], []
            for f in fams[:4]:
                rel = facts[f]["tables"][t][0][0]
                paths.append("%s/%s" % (f, rel))
                fs.append(f)
            add("cross_repo_trace", "%s 表 哪些服务 读写 跨服务" % t, fs, paths,
                ["表 %s 在 %s 等服务中被引用" % (t, "、".join(fs))],
                "answer", "跨族 Mapper/DDL 同名表")
            cross += 1

    # 3) document_reasoning：正文限制/例外句成题；查询词排除标题与文件名
    dr = 0
    for f in sorted(facts):
        for doc in facts[f]["docs"]:
            if doc.get("mock_ratio", 0) > MOCK_MAX:
                continue  # mock/占位页不入 gold（第 5 步诊断：曾致假 recall miss）
            if dr >= QUOTA["document_reasoning"]:
                break
            restrict = [s for s in doc["sentences"]
                        if any(k in s for k in RESTRICT_KW)]
            if not restrict:
                continue
            words = topic_words(doc)
            if len(words) < 3:
                continue
            add("document_reasoning", " ".join(words[:6]) + " 限制 条件", [f],
                ["%s/%s" % (f, doc["rel"])],
                ["%s：%s" % (doc["rel"], restrict[0][:80])],
                "answer", "正文限制句；查询词排除标题/文件名（topic_words）")
            dr += 1
        if dr >= QUOTA["document_reasoning"]:
            break

    # 4) knowledge_freshness：文档内最新日期/版本（无 mtime）；每族最多 3 个不同文档
    kf = 0
    for f in sorted(facts):
        dated = sorted((d for d in facts[f]["docs"]
                        if d["dates"] and d.get("mock_ratio", 0) <= MOCK_MAX),
                       key=lambda d: max(d["dates"]), reverse=True)
        used = 0
        for newest in dated:
            if kf >= QUOTA["knowledge_freshness"] or used >= 3:
                break
            latest = max(newest["dates"])
            date_str = "%d-%02d-%02d" % latest
            words = topic_words(newest)
            if len(words) < 2:
                continue
            add("knowledge_freshness",
                " ".join(words[:5]) + " 最新 生效 说明 日期", [f],
                ["%s/%s" % (f, newest["rel"])],
                ["%s 内最新日期 %s" % (newest["rel"], date_str)],
                "answer", "文档内日期扫描（DATE 正则，非 mtime）")
            kf += 1
            used += 1

    # 5) locator_diagnostic：旧式标题/README 检索，单列诊断
    loc = 0
    for f in sorted(facts):
        for title, rel in facts[f]["locators"]:
            if loc >= QUOTA["locator_diagnostic"]:
                break
            add("locator_diagnostic", title, [f], ["%s/%s" % (f, rel)],
                ["标题/README 检索命中 %s" % rel], "answer",
                "标题检索（diagnostic-only：不冒充文档推理）")
            loc += 1
        if loc >= QUOTA["locator_diagnostic"]:
            break

    # 6) negative 四因
    real_tables = set(by_table)
    made = {"no_evidence": 0, "near_name": 0, "ambiguous": 0, "wrong_scope": 0}
    absent_pool = ["冷链温控巡检", "对账差异自动核销", "拼团成团率看板", "直播弹幕审核",
                   "会员积分冻结解冻", "跨境清关回执归档", "门店盘点差异分摊", "运费险理赔抄件",
                   "预售尾款催付策略", "以旧换新质检拍照"]
    for term in absent_pool:
        if made["no_evidence"] >= 10:
            break
        found = False
        for f in facts:  # 全工作区 grep 验证缺失
            for doc in facts[f]["docs"]:
                if term in " ".join(doc["tokens"]):
                    found = True
                    break
            if found:
                break
        if not found:
            add("negative", "%s 规则 配置" % term, [], [], [],
                "abstain", "无证据：全工作区正文扫描未见该业务词")
            made["no_evidence"] += 1
    for t in sorted(real_tables):
        if made["near_name"] >= 10:
            break
        mut = t[:-2] + "qq" if len(t) > 6 else t[:2] + "zz" + t[3:]
        if mut in real_tables or any(mut in " ".join(facts[f]["tables"]) for f in facts):
            continue
        add("negative", "%s 表 定义" % mut, [], [], [],
            "abstain", "近名：编辑距离变形且全表名集合/正文未出现")
        made["near_name"] += 1
    amb = {}
    for f in facts:
        for name, _rel, _c in facts[f]["classes"]:
            amb.setdefault(name, []).append(f)
    for name in sorted(amb):
        if made["ambiguous"] >= 10:
            break
        fams = sorted(set(amb[name]))
        if len(fams) >= 2:
            add("negative", "%s 类 定义 唯一 位置" % name, [], [],
                ["同名类存在于 %s ——应 clarify" % "、".join(fams[:3])],
                "clarify", "歧义：同名类 ≥2 族（已验证存在）")
            made["ambiguous"] += 1
    fam_list = sorted(facts)
    table_fams = {t: sorted(set(fs)) for t, fs in by_table.items()}
    for t in sorted(table_fams):
        if made["wrong_scope"] >= 10 or len(fam_list) < 2:
            break
        owner = table_fams[t][0]
        other = next((f for f in fam_list if f not in table_fams[t]), None)
        if not other:
            continue
        if t not in facts[other]["tables"]:
            add("negative", "%s 表 %s 中的配置" % (t, other), [], [], [],
                "abstain", "错范围：表仅存在于 %s，目标族表集合已验证无此表" % owner)
            made["wrong_scope"] += 1

    counts = {}
    for q in questions:
        counts[q["category"]] = counts.get(q["category"], 0) + 1
    return questions, gold, counts


def main():
    fams = sorted(d for d in os.listdir(WS)
                  if os.path.isdir(os.path.join(WS, d)) and not d.startswith("."))
    # 注：四个外部文档族（deepseek-harness/zhiyu 等）各 1.8-2.0GB，扫描代价过高且非
    # 目标负载（Java/Mapper+中文文档）；dev v2 收敛到 dev-corp 45 族，文档类配额由 文档族 承担。
    questions, gold, counts = build(fams)
    os.makedirs(OUTDIR, exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    qpayload = {"schema": "domimap.dev-questions.v2", "generated_utc": stamp,
                "generator": "benchmarks/corpus/generate_questions_v2.py",
                "counts": counts, "questions": questions}
    gpayload = {"schema": "domimap.dev-gold.v2", "generated_utc": stamp,
                "limitations": ["机械草稿 gold（grep/正则级），供 dev 诊断；不作为独立裁决输入",
                                 "gold 与 questions 分文件；运行器拒收 gold 字段"],
                "gold": gold}
    json.dump(qpayload, open(os.path.join(OUTDIR, "dev-questions-v2.json"), "w",
                             encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(gpayload, open(os.path.join(OUTDIR, "dev-gold-v2.json"), "w",
                             encoding="utf-8"), ensure_ascii=False, indent=1)
    print("questions=%d counts=%s" % (len(questions), counts))
    print("answerable=%d negative=%d → %s" % (
        sum(1 for g in gold if g["disposition"] != "abstain" or g["disposition"] == "clarify"),
        counts.get("negative", 0), OUTDIR))


if __name__ == "__main__":
    main()
