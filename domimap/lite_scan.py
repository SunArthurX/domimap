"""lite_scan — 确定性扫描层 + 5 个 synthesizer 的原始记录抽取。

全部为正则/XML 确定性规则（MVP；graphify AST 引擎就绪后由 build.py 热切换增强）。
每条记录带 provenance（文件+规则名），对应方案的置信体系：
  EXTRACTED  = 从源码/XML 结构直接抽出（XML 用解析器）
  INFERRED   = 正则/启发式合成（需 golden 测试守护）
"""
import os
import re
import xml.etree.ElementTree as ET

SKIP_DIRS = {".git", "node_modules", "target", "build", "dist", ".idea", ".vault-meta", "graphify-out", "__pycache__"}
CODE_EXT = {".java", ".xml", ".ts", ".tsx", ".js", ".jsx", ".vue", ".sql"}
DOC_EXT = {".md", ".txt"}
BIG = 2 * 1024 * 1024

# ---------- Spring 注解 → HTTP method ----------
_SPRING_MAP = [
    ("GetMapping", "GET"), ("PostMapping", "POST"), ("PutMapping", "PUT"),
    ("DeleteMapping", "DELETE"), ("PatchMapping", "PATCH"),
]
_RE_MAPPING = re.compile(r'@(Request|Get|Post|Put|Delete|Patch)Mapping\s*\(\s*(?:value\s*=\s*)?"([^"]*)"')
_RE_MAPPING_ANY = re.compile(r'@(Request|Get|Post|Put|Delete|Patch)Mapping\s*\(\s*(?:value\s*=\s*)?"([^"]*)"|@RequestMapping\s*\(\s*(?:value\s*=\s*)?"([^"]*)"')
_RE_CLASS = re.compile(r'(?:public\s+)?(?:abstract\s+)?class\s+(\w+)|(?:public\s+)?interface\s+(\w+)')
# 类型段必须以非空白开头：裸调用行（如 `    changePrice(1L, x);`）不得被当作方法声明
_RE_METHOD_LINE = re.compile(r'^\s*(?:(?:public|protected|private|static|final|synchronized|default|abstract)\s+)*'
                             r'[\w<>\[\],.][\w<>\[\],.\s]*?\s+(\w+)\s*\(')
_RE_PKG = re.compile(r'^\s*package\s+([\w\.]+)\s*;', re.M)
_RE_DUBBO_SVC = re.compile(r'@DubboService\b|@org\.apache\.dubbo.*Service\b')
_RE_DUBBO_REF = re.compile(r'@(?:[\w.]+\.)?DubboReference\s*(?:\([^)]*\))?\s*\n?\s*(?:private|protected|public)?\s*([\w\.]+?)\s+(\w+)\s*;')
_RE_MQ_LISTEN = re.compile(r'@RocketMQMessageListener\s*\(([^)]*)\)', re.S)
_RE_MQ_TOPIC = re.compile(r'topic\s*=\s*"([^"]+)"')
_RE_MQ_SEND = re.compile(r'(?:rocketMQTemplate|rocketMqTemplate)\s*\.\s*(?:syncSend|asyncSend|send|convertAndSend)\s*\(\s*"([^"]+)"')
_RE_FEIGN = re.compile(r'@(FeignClient|DubboReference)\s*\(([^)]*)\)', re.S)
_RE_FEIGN_NAME = re.compile(r'(?:name|value)\s*=\s*"([^"]+)"')
# 前端调用（fetch/axios）
_RE_FETCH = re.compile(r"""(?:fetch|axios(?:\.(?:get|post|put|delete|patch))?)\s*\(\s*['"`]([^'"`]+)['"`]([^)]{0,80})""")
# 通用 MQ 监听（Kafka/Rabbit/JMS/Spring event）
_RE_GEN_LISTEN = re.compile(r'@(KafkaListener|RabbitListener|JmsListener|StreamListener|RabbitHandler)\s*\(([^)]*)\)', re.S)
_RE_GEN_TOPIC = re.compile(r'(?:topics?|queues?|destination|value)\s*=\s*(?:"([^"]+)"|\{([^}]*)\})')
# JPA 实体
_RE_ENTITY = re.compile(r'@Entity\b')
_RE_TABLE = re.compile(r'@Table\s*\(\s*name\s*=\s*"([^"]+)"')
_RE_JPA_COL = re.compile(r'@Column\s*\(\s*name\s*=\s*"([^"]+)"[^)]*\)\s*\n?\s*(?:private|protected|public)\s+[\w.<>\[\]]+\s+(\w+)')
# 方法级调用（lite）：接收者.方法( 形态；接收者按"字段声明类型 → 已知类名小驼峰"解析（link_calls 二遍法）
_RE_CALL = re.compile(r'\b([a-z]\w*)\.(\w+)\s*\(')
_RE_FIELD = re.compile(r'(?:private|protected|public)\s+(?:final\s+)?([\w.]+)\s+(\w+)\s*;')
_RE_LAMBDA_LINE = re.compile(r'->|new\s+\w+\s*\([^)]*\)\s*\{')
SKIP_RECV = {"this", "super", "system", "math", "objects", "string", "integer",
             "long", "boolean", "double", "log", "logger", "strings", "collections"}

def _walk(root, on_skip=None):
    """遍历登记根内文件。symlink 解析后越界（D3）与大文件跳过经 on_skip 显式上报，不静默。"""
    root_real = os.path.realpath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if os.path.islink(p):
                real = os.path.realpath(p)
                inside = real == root_real or real.startswith(root_real + os.sep)
                if not inside:
                    if on_skip:
                        on_skip({"file": os.path.relpath(p, root),
                                 "reason": "越界 symlink 拒绝（指向登记根外）", "target": real})
                    continue
            if st.st_size > BIG:
                if on_skip:
                    on_skip({"file": os.path.relpath(p, root), "reason": "超过大小上限"})
                continue
            yield p, os.path.relpath(p, root)

_GENERIC_DIRS = {"src", "main", "java", "resources", "test", "tests", "docs", "doc",
                 "db", "sql", "conf", "config", "h5", "web", "front", "bin", "lib", "meta-inf",
                 "com", "org", "net", "cn", "io", "javax", "sun", "static", "public"}

def _service_of(rel):
    """服务目录推断：首个非通用目录段；根级文件回退空（调用方用 repo_label）。"""
    parts = rel.replace("\\", "/").split("/")
    for p in parts[:-1]:
        if p not in _GENERIC_DIRS and not p.startswith("."):
            return p
    return ""

def scan_repo(root, repo_label=None):
    """返回 records dict。多仓合并时传 repo_label，服务名变为 "label:子模块"。"""
    R = {"services": {}, "classes": [], "methods": [], "routes": [], "rpc": [],
         "topics": [], "sqlstmts": [], "tables": [], "pages": [], "docs": [], "entities": [],
         "raw_calls": [], "calls": [],
         "coverage": {"files_scanned": 0, "skipped": []}}
    routes_by_class = {}
    for path, rel in _walk(root, on_skip=R["coverage"]["skipped"].append):
        ext = os.path.splitext(rel)[1].lower()
        if ext not in CODE_EXT and ext not in DOC_EXT and ext not in {".docx", ".pdf", ".doc"}:
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        R["coverage"]["files_scanned"] += 1
        svc = _service_of(rel)
        if not svc:
            svc = repo_label or "(root)"
        elif repo_label:
            svc = repo_label + ":" + svc
        R["services"].setdefault(svc, {"file": svc, "classes": 0})
        if ext == ".java":
            _scan_java(R, path, rel, svc, text, routes_by_class)
        elif ext == ".xml" and ("<mapper" in text or "<sqlMap" in text):
            _scan_mybatis(R, path, rel, svc, text)
        elif ext in {".ts", ".tsx", ".js", ".jsx", ".vue"}:
            _scan_front(R, path, rel, svc, text)
        elif ext == ".sql":
            _scan_sql(R, path, rel, text)
        elif ext in DOC_EXT:
            meta = {}
            if text.startswith("---"):  # front-matter：valid_until/superseded_by（F4 时间资格）
                for ln in text.split("---")[1].split("\n")[:12]:
                    if ":" in ln:
                        k, _, v = ln.partition(":")
                        if k.strip() in ("valid_until", "superseded_by"):
                            meta[k.strip()] = v.strip()
            R["docs"].append({"path": rel, "text": text[:200000], "service": svc, **meta})
        elif ext == ".docx":
            t = _docx_text(path)
            if t is None:
                R["coverage"]["skipped"].append({"file": rel, "reason": "python-docx 未安装（可选依赖）"})
            else:
                R["docs"].append({"path": rel, "text": t[:200000]})
        elif ext == ".pdf":
            t = _pdf_text(path)
            if t is None:
                R["coverage"]["skipped"].append({"file": rel, "reason": "pypdf 未安装（可选依赖）"})
            else:
                R["docs"].append({"path": rel, "text": t[:200000]})
        elif ext == ".doc":
            R["coverage"]["skipped"].append({"file": rel, "reason": ".doc 旧格式：请先 `soffice --headless --convert-to docx`"})
    link_calls(R)
    return R

def _lower_first(s):
    return s[0].lower() + s[1:] if s else s

def _argc_of(line, meth):
    """声明行内取参数个数；跨行签名返回 -1（显式未知，不猜）。"""
    i = line.find(meth + "(")
    if i < 0:
        return -1
    rest = line[i + len(meth) + 1:]
    j = rest.find(")")
    if j < 0:
        return -1
    inner = rest[:j].strip()
    if not inner:
        return 0
    depth = 0
    count = 1
    for ch in inner:
        if ch in "(<[":
            depth += 1
        elif ch in ")>]":
            depth -= 1
        elif ch == "," and depth == 0:
            count += 1
    return count

def link_calls(R):
    """二遍法：接收者解析顺序 = 文件内字段声明类型 → 类名小驼峰；目标为重载多候选时
    conf=AMBIGUOUS（不默取第一个），无候选不产边（未知可见）。"""
    recv2cls = {_lower_first(c["name"]): c["name"] for c in R["classes"]}
    fields = {}
    for f in R.get("fields", []):
        fields.setdefault(f["var"], f["type"].split(".")[-1])
    mth_index = {}
    for m in R["methods"]:
        mth_index.setdefault((m["service"], m["cls"], m["name"]), []).append(m.get("argc", -1))
    for rc in R.pop("raw_calls", []):
        recv_cls = fields.get(rc["recv"]) or recv2cls.get(rc["recv"]) or \
            (rc["from_cls"] if rc["recv"] == "" else None)
        if not recv_cls:
            continue
        cand = mth_index.get((rc["service"], recv_cls, rc["to"]))
        if not cand:
            continue
        rec = {"from": rc["from"], "from_cls": rc["from_cls"], "from_argc": rc["from_argc"],
               "to_method": rc["to"], "to_cls": recv_cls, "recv": rc["recv"],
               "to_argcs": sorted(set(cand)), "service": rc["service"], "file": rc["file"],
               "prov": "synth:java-call", "conf": "INFERRED" if len(set(cand)) == 1 else "AMBIGUOUS"}
        if len(set(cand)) > 1:
            rec["prov"] = "synth:java-call+overload-unknown"
        R["calls"].append(rec)

def _scan_java(R, path, rel, svc, text, routes_by_class):
    pkg = (_RE_PKG.search(text) or [None, ""])[1]
    for m in _RE_CLASS.finditer(text):
        name = m.group(1) or m.group(2)
        is_ctrl = "@RestController" in text or "@Controller" in text
        R["classes"].append({"name": name, "fqn": (pkg + "." + name) if pkg else name,
                             "service": svc, "file": rel, "rest_controller": is_ctrl,
                             "dubbo_service": bool(_RE_DUBBO_SVC.search(text)),
                             "prov": "java:class"})
        R["services"][svc]["classes"] += 1
        # 类级路由前缀
        cm = re.search(r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?"([^"]*)"\s*\)', text[:m.start() + 2000])
        routes_by_class[name] = cm.group(1) if cm else ""
        break  # MVP：每文件取首个主类
    for fm in _RE_FIELD.finditer(text):
        R.setdefault("fields", []).append({"type": fm.group(1), "var": fm.group(2),
                                           "service": svc, "file": rel})
    # 方法 + 路由 + MQ 发送 + Dubbo 引用（逐行匹配声明；接口方法无修饰符也可命中）
    is_ctrl = "@RestController" in text or "@Controller" in text
    class_ranges = [(m.start(), m.group(1) or m.group(2)) for m in _RE_CLASS.finditer(text)]

    def cls_at(offset):
        cur = ""
        for start, name in class_ranges:
            if start <= offset:
                cur = name
            else:
                break
        return cur

    def anonymous_at(offset):
        """方法声明处于匿名内部类体内（其上方最近 new X(){..{ 多于 }）→ 归 (anonymous)，不假归属外层。"""
        seg = text[max(0, offset - 300):offset]
        m = None
        for m in re.finditer(r'new\s+[\w.]+(?:<[^>]*>)?\s*\([^)]*\)\s*\{', seg):
            pass
        if not m:
            return False
        tail = seg[m.start():]
        return tail.count("{") > tail.count("}")

    entries = []
    for ln, line in enumerate(text.split("\n"), 1):
        mm = _RE_METHOD_LINE.match(line)
        if not mm or mm.group(1) in {"if", "for", "while", "switch", "catch", "return", "new", "throw"}:
            continue
        meth = mm.group(1)
        off = text.find(line)
        cls_here = "(anonymous)" if anonymous_at(off) else cls_at(off)
        entries.append({"name": meth, "off": off, "ln": ln, "cls": cls_here,
                        "argc": _argc_of(line, meth)})
        R["methods"].append({"name": meth, "cls": cls_here, "argc": _argc_of(line, meth),
                             "service": svc, "file": rel, "line": ln, "prov": "java:method"})
    for ent in entries:
        meth, off, ln, cur_cls, argc = ent["name"], ent["off"], ent["ln"], ent["cls"], ent["argc"]
        line = text.split("\n")[ln - 1]
        if is_ctrl:
            seg = text[max(0, text.find(line) - 400):text.find(line)]
            anns = list(_RE_MAPPING_ANY.finditer(seg))
            if anns:
                am = anns[-1]  # 取距方法最近的注解（方法级优先于类级）
                prefix = ""
                for cls, pf in routes_by_class.items():
                    if cls in text:
                        prefix = pf
                        break
                http = dict(_SPRING_MAP).get((am.group(1) or "") + "Mapping", "ANY")
                pathv = am.group(2) or am.group(3) or ""
                R["routes"].append({"method": http, "path": (prefix or "") + pathv,
                                    "java_method": meth, "cls": cur_cls, "argc": argc, "service": svc,
                                    "file": rel, "prov": "synth:spring-route", "conf": "INFERRED"})
        body = text[text.find(line):text.find(line) + 3000]
        for sm in _RE_MQ_SEND.finditer(body):
            R["topics"].append({"topic": sm.group(1), "dir": "PUBLISHES", "by": meth, "cls": cur_cls,
                                "argc": argc, "service": svc, "file": rel,
                                "prov": "synth:rocketmq-send", "conf": "INFERRED"})
        # lambda/匿名类行内的调用保守跳过（不假归属外层方法），显式记 coverage
        for bl in body.split("\n"):
            for cm in _RE_CALL.finditer(bl):
                recv, callee = cm.group(1), cm.group(2)
                if recv in SKIP_RECV:
                    continue
                if _RE_LAMBDA_LINE.search(bl):
                    if not R["coverage"]["skipped"] or R["coverage"]["skipped"][-1].get("file") != rel or \
                           "lambda" not in R["coverage"]["skipped"][-1].get("reason", ""):
                        R["coverage"]["skipped"].append(
                            {"file": rel, "reason": "lambda/匿名上下文调用未解析（保守跳过，不归属外层方法）"})
                    continue
                R["raw_calls"].append({"from": meth, "from_cls": cur_cls, "from_argc": argc,
                                       "recv": recv, "to": callee, "service": svc, "file": rel})
        # 同类裸调用（两遍法已见全部方法，含前向声明；lambda/匿名行保守跳过并记录）
        for other in [m for m in R["methods"] if m.get("cls") == cur_cls and m["name"] != meth]:
            pat = re.compile(r'(?<![\w.])' + re.escape(other["name"]) + r'\s*\(')
            hit_lambda = False
            hit_plain = False
            for bl in body.split("\n"):
                if not pat.search(bl):
                    continue
                if _RE_METHOD_LINE.match(bl):
                    continue  # 声明行不是调用点
                if _RE_LAMBDA_LINE.search(bl):
                    hit_lambda = True
                else:
                    hit_plain = True
            if hit_plain:
                R["raw_calls"].append({"from": meth, "from_cls": cur_cls, "from_argc": argc,
                                       "recv": "", "to": other["name"], "service": svc, "file": rel})
            if hit_lambda:
                R["coverage"]["skipped"].append(
                    {"file": rel, "reason": "lambda/匿名上下文调用未解析（保守跳过，不归属外层方法）"})
    # MQ 监听（类级）
    for lm in _RE_MQ_LISTEN.finditer(text):
        tm = _RE_MQ_TOPIC.search(lm.group(1))
        if tm:
            cm = _RE_CLASS.search(text)
            cls = (cm.group(1) or cm.group(2)) if cm else "Listener"
            R["topics"].append({"topic": tm.group(1), "dir": "SUBSCRIBES", "by": cls,
                                "service": svc, "file": rel, "prov": "synth:rocketmq-listener", "conf": "EXTRACTED"})
    # 通用 MQ 监听（Kafka/Rabbit/JMS）
    for lm in _RE_GEN_LISTEN.finditer(text):
        ann, arg = lm.group(1), lm.group(2)
        tm = _RE_GEN_TOPIC.search(arg)
        if not tm:
            continue
        topics = [tm.group(1)] if tm.group(1) else re.findall(r'"([^"]+)"', tm.group(2) or "")
        cm0 = _RE_CLASS.search(text)
        cls = (cm0.group(1) or cm0.group(2)) if cm0 else "Listener"
        for tp in topics:
            R["topics"].append({"topic": tp, "dir": "SUBSCRIBES", "by": cls,
                                "service": svc, "file": rel, "prov": "synth:" + ann, "conf": "EXTRACTED"})
    # JPA 实体：@Entity + @Table(name) + @Column(name)
    if _RE_ENTITY.search(text):
        cm0 = _RE_CLASS.search(text)
        cls = (cm0.group(1) or cm0.group(2)) if cm0 else None
        tm = _RE_TABLE.search(text)
        cols = [c[0] for c in _RE_JPA_COL.findall(text)]
        if cls:
            R["entities"].append({"cls": cls, "table": tm.group(1) if tm else cls,
                                  "cols": cols, "service": svc, "file": rel,
                                  "prov": "synth:jpa", "conf": "EXTRACTED"})
    # Dubbo 消费（@Reference 字段）
    for rm in _RE_DUBBO_REF.finditer(text):
        R["rpc"].append({"iface": rm.group(1).split(".")[-1], "role": "consumer",
                         "service": svc, "file": rel, "prov": "synth:dubbo-ref", "conf": "INFERRED"})
    for fm in _RE_FEIGN.finditer(text):
        nm = _RE_FEIGN_NAME.search(fm.group(2))
        if nm:
            R["rpc"].append({"iface": nm.group(1), "role": "consumer", "kind": fm.group(1),
                             "service": svc, "file": rel, "prov": "synth:feign", "conf": "INFERRED"})

def _scan_mybatis(R, path, rel, svc, text):
    try:
        tree = ET.fromstring(text)
    except ET.ParseError:
        R["coverage"]["skipped"].append({"file": rel, "reason": "mapper XML 解析失败"})
        return
    ns = tree.get("namespace", "")
    iface = ns.split(".")[-1]
    for stmt in tree.iter():
        tag = stmt.tag.split("}")[-1]
        if tag in {"select", "insert", "update", "delete"}:
            sid = stmt.get("id", "")
            # 动态 SQL（<if>/<foreach>）：取全部后代文本节点，标签即动态结构
            sql = " ".join(t.strip() for t in stmt.itertext() if t and t.strip())
            tables = set(re.findall(r'(?:FROM|JOIN|INTO|UPDATE)\s+`?(\w+)`?', sql, re.I))
            cols = set(re.findall(r'(\w+)\s*=', sql))
            R["sqlstmts"].append({"iface": iface, "id": sid, "verb": tag.upper(), "sql": sql[:500],
                                  "tables": sorted(tables), "cols": sorted(cols)[:30],
                                  "service": svc, "file": rel, "prov": "synth:mybatis", "conf": "EXTRACTED"})

def _scan_front(R, path, rel, svc, text):
    for fm in _RE_FETCH.finditer(text):
        url, tail = fm.group(1), fm.group(2)
        method = "GET"
        mm = re.search(r"method\s*:\s*['\"](\w+)['\"]", tail)
        if mm:
            method = mm.group(1).upper()
        elif "axios.post" in fm.group(0) or ".post(" in fm.group(0):
            method = "POST"
        R["pages"].append({"url": url, "method": method, "file": rel, "service": svc,
                           "prov": "synth:crossend", "conf": "INFERRED"})

def _scan_sql(R, path, rel, text):
    for m in re.finditer(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(\w+)`?\s*\((.*?)\)\s*(?:ENGINE|;|$)', text, re.I | re.S):
        tbl = m.group(1)
        cols = [c for c in re.findall(r'^\s*`?(\w+)`?\s+\w+', m.group(2), re.M)
                if c.upper() not in {'PRIMARY', 'UNIQUE', 'KEY', 'INDEX', 'CONSTRAINT', 'FOREIGN', 'CREATE'}]
        R["tables"].append({"table": tbl, "cols": cols, "file": rel, "prov": "sql:ddl", "conf": "EXTRACTED"})

def _docx_text(path):
    try:
        import docx
        d = docx.Document(path)
        return "\n".join(p.text for p in d.paragraphs)
    except Exception:
        return None

def _pdf_text(path):
    try:
        from pypdf import PdfReader
        r = PdfReader(path)
        return "\n".join((pg.extract_text() or "") for pg in r.pages)
    except Exception:
        return None
