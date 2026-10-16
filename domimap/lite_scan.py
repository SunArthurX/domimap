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
_RE_METHOD_LINE = re.compile(r'^\s*(?:(?:public|protected|private|static|final|synchronized|default|abstract)\s+)*'
                             r'[\w<>\[\],.\s]+?\s+(\w+)\s*\(')
_RE_PKG = re.compile(r'^\s*package\s+([\w\.]+)\s*;', re.M)
_RE_DUBBO_SVC = re.compile(r'@DubboService\b|@org\.apache\.dubbo.*Service\b')
_RE_DUBBO_REF = re.compile(r'@DubboReference\s*(?:\([^)]*\))?\s*\n?\s*(?:private|protected|public)?\s*([\w\.]+?)\s+(\w+)\s*;')
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
# 方法级调用（lite）：接收者.方法( 形态；接收者按"已知类名小驼峰"解析（link_calls 二遍法）
_RE_CALL = re.compile(r'\b([a-z]\w*)\.(\w+)\s*\(')
SKIP_RECV = {"this", "super", "system", "math", "objects", "string", "integer",
             "long", "boolean", "double", "log", "logger", "strings", "collections"}

def _walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if st.st_size > BIG:
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
    for path, rel in _walk(root):
        ext = os.path.splitext(rel)[1].lower()
        if ext not in CODE_EXT and ext not in DOC_EXT and ext not in {".docx", ".pdf"}:
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
            R["docs"].append({"path": rel, "text": text[:200000]})
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

def link_calls(R):
    """二遍法：walk 结束后类名 registry 齐全，把 raw_calls 的接收者解析为已知类（小驼峰同名）。
    仅当接收者命中已知类才合成（INFERRED）；被调方法节点是否存在由 graph 层把门。"""
    recv2cls = {_lower_first(c["name"]): c["name"] for c in R["classes"]}
    for rc in R.pop("raw_calls", []):
        if rc["recv"] in recv2cls:
            R["calls"].append({"from": rc["from"], "to_method": rc["to"], "recv": rc["recv"],
                               "service": rc["service"], "file": rc["file"],
                               "prov": "synth:java-call", "conf": "INFERRED"})

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
    # 方法 + 路由 + MQ 发送 + Dubbo 引用（逐行匹配声明；接口方法无修饰符也可命中）
    is_ctrl = "@RestController" in text or "@Controller" in text
    for ln, line in enumerate(text.split("\n"), 1):
        mm = _RE_METHOD_LINE.match(line)
        if not mm or mm.group(1) in {"if", "for", "while", "switch", "catch", "return", "new", "throw"}:
            continue
        meth = mm.group(1)
        R["methods"].append({"name": meth, "service": svc, "file": rel, "line": ln,
                             "prov": "java:method"})
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
                                    "java_method": meth, "service": svc, "file": rel,
                                    "prov": "synth:spring-route", "conf": "INFERRED"})
        body = text[text.find(line):text.find(line) + 3000]
        for sm in _RE_MQ_SEND.finditer(body):
            R["topics"].append({"topic": sm.group(1), "dir": "PUBLISHES", "by": meth,
                                "service": svc, "file": rel, "prov": "synth:rocketmq-send", "conf": "INFERRED"})
        for cm in _RE_CALL.finditer(body):
            recv, callee = cm.group(1), cm.group(2)
            if recv not in SKIP_RECV:
                R["raw_calls"].append({"from": meth, "recv": recv, "to": callee,
                                       "service": svc, "file": rel})
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
            sql = " ".join((stmt.text or "").split())
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
