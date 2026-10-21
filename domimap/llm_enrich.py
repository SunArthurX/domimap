"""llm_enrich — 可选的大模型语义增强层（R05 草稿纪律；产品任务 product-llm-enrich）。

确定性解析（lite_scan/graph）的事实图不受本模块影响。本层把图内 Doc 材料交给
可配置的 LLM（anthropic messages 协议，默认 bigmodel/glm-5.3）做摘要/关键词/
主张抽取；产物一律是 inference 型草稿笔记（KnowledgeStore，state=proposed，
带 LLM 标注），人工审定（accept/confirm）后才升级——推断永不混为事实（AC-R05-02）。

配置（flag > 环境变量 > 默认）：
  DOMIMAP_LLM_ENDPOINT（默认 https://open.bigmodel.cn/api/anthropic/v1/messages）
  DOMIMAP_LLM_MODEL（默认 glm-5.3） / DOMIMAP_LLM_MAX_TOKENS（默认 1024）
  key：GLM_API_KEY 或 ANTHROPIC_API_KEY；否则 DOMIMAP_LLM_KEY_HELPER 指向的
  本机模块（提供 load_api_key()）。无配置时抛 LlmConfigError（CLI 退出码 6）。
"""
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request

DEFAULT_ENDPOINT = "https://open.bigmodel.cn/api/anthropic/v1/messages"
DEFAULT_MODEL = "glm-5.3"
KEY_ENV_VARS = ("GLM_API_KEY", "ANTHROPIC_API_KEY")
MAX_LIMIT = 50          # 单次条数上限（R08 资源纪律）
MAX_MATERIAL_CHARS = 20000  # 单篇材料硬上限

SYSTEM_PROMPT = (
    "你是代码库知识整理助手。只依据用户给出的材料整理，不得引入材料之外的事实，"
    "不得编造文件路径。只输出一个 JSON 对象（无额外说明），结构为：\n"
    '{"summary": "3-5 句中文摘要", "keywords": ["中文和英文关键词"], '
    '"claims": [{"statement": "一句话可核验的主张", "evidence_paths": ["材料中出现的路径"]}]}\n'
    "claims 最多 5 条；evidence_paths 只能取材料里给出的路径；keywords 最多 8 个。")


class LlmConfigError(RuntimeError):
    """未配置 key/端点等——调用方应干净退出，不静默降级。"""


def load_api_key():
    for name in KEY_ENV_VARS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    helper = os.environ.get("DOMIMAP_LLM_KEY_HELPER", "").strip()
    if helper:
        path = os.path.expanduser(helper)
        if not os.path.isfile(path):
            raise LlmConfigError("DOMIMAP_LLM_KEY_HELPER 指向的模块不存在：%s" % path)
        import importlib.util
        spec = importlib.util.spec_from_file_location("domimap_llm_key_helper", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.load_api_key()
    raise LlmConfigError(
        "未配置大模型 key：请设置 GLM_API_KEY / ANTHROPIC_API_KEY，"
        "或 DOMIMAP_LLM_KEY_HELPER 指向提供 load_api_key() 的本机模块")


class LlmClient:
    """anthropic messages 协议最小客户端（stdlib urllib；transport 可注入供测试）。"""

    def __init__(self, endpoint=None, model=None, api_key=None, max_tokens=None,
                 timeout=120, retries=3, transport=None):
        self.endpoint = endpoint or os.environ.get("DOMIMAP_LLM_ENDPOINT") or DEFAULT_ENDPOINT
        self.model = model or os.environ.get("DOMIMAP_LLM_MODEL") or DEFAULT_MODEL
        self.max_tokens = int(max_tokens or os.environ.get("DOMIMAP_LLM_MAX_TOKENS") or 1024)
        self.api_key = api_key
        self.timeout = timeout
        self.retries = retries
        self._transport = transport or self._http_post

    def _http_post(self, payload):
        req = urllib.request.Request(
            self.endpoint, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "x-api-key": self.api_key,
                     "anthropic-version": "2023-06-01"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read())

    def _send(self, payload):
        """瞬时网络故障有界重试（无论真实 HTTP 还是注入的测试传输）。"""
        last = None
        for attempt in range(self.retries):
            try:
                return self._transport(payload)
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                last = error
                if attempt + 1 < self.retries:
                    time.sleep(1.5 * (attempt + 1))
        raise last

    def complete(self, system, user):
        """返回 (拼接的 text 块, usage)。thinking/tool 等非文本块被跳过。

        真实端点 content 在顶层；测试桩可用 message.content 嵌套（两者兼容）。
        """
        resp = self._send({
            "model": self.model, "max_tokens": self.max_tokens, "system": system,
            "messages": [{"role": "user", "content": user}]})
        content = resp.get("content") or (resp.get("message") or {}).get("content") or []
        texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
        return "\n".join(t for t in texts if t), resp.get("usage") or {}


def parse_llm_json(text):
    """宽容提取响应中的 JSON 对象；失败抛 ValueError（调用方记错误并继续）。"""
    text = (text or "").strip()
    candidates = [text]
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        candidates.append(fenced.group(1))
    braces = re.search(r"\{.*\}", text, re.S)
    if braces:
        candidates.append(braces.group(0))
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except ValueError:
            continue
        if (isinstance(obj, dict) and isinstance(obj.get("summary"), str)
                and obj["summary"].strip()):
            return obj
    raise ValueError("响应中未找到含 summary 的合法 JSON")


def select_targets(g, limit, min_chars=200):
    """Doc 节点按材料长度降序取前 limit（图内 meta.text，无需读盘）。"""
    docs = [n for n in g.nodes.values()
            if n["kind"] == "Doc" and len(n.get("meta", {}).get("text") or "") >= min_chars]
    docs.sort(key=lambda n: -len(n["meta"]["text"]))
    return docs[:max(0, min(int(limit), MAX_LIMIT))]


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_note(model, doc, text_sha, parsed):
    from .knowledge import LLM_NOTE_PREFIX
    keywords = [str(k) for k in (parsed.get("keywords") or [])][:8]
    lines = [LLM_NOTE_PREFIX + "model=%s｜source=%s｜text_sha=%s】" % (model, doc["file"], text_sha[:16]),
             parsed["summary"].strip()]
    if keywords:
        lines.append("关键词：" + ", ".join(keywords))
    claims = []
    for c in (parsed.get("claims") or [])[:5]:
        if not isinstance(c, dict) or not str(c.get("statement", "")).strip():
            continue
        paths = [str(p) for p in (c.get("evidence_paths") or []) if str(p).strip()][:3]
        claims.append({"type": "inference",
                       "statement": str(c["statement"]).strip(),
                       "evidence": paths, "scope": doc["file"]})
    return "\n".join(lines), claims


def enrich(graph_path, limit=5, model=None, endpoint=None, max_tokens=None,
           cap=8000, dry_run=False, force=False, client=None):
    """编排：选目标 → （幂等）调用 → 解析 → 写 knowledge.db + enrichment.json 审计。

    client 可注入（测试）；dry_run 只组装提示并打印统计，不联网不落库不写文件。
    """
    from .graph import Graph
    from .knowledge import KnowledgeStore

    g = Graph.load(graph_path)
    targets = select_targets(g, limit)
    base = os.path.dirname(os.path.abspath(graph_path))
    audit_path = os.path.join(base, "enrichment.json")
    audit = {"schema": "domimap.llm-enrich.v1", "updated": time.time(), "entries": []}
    if os.path.exists(audit_path):
        try:
            audit = json.load(open(audit_path, encoding="utf-8"))
        except (OSError, ValueError):
            pass
    done_keys = {e["key"] for e in audit.get("entries", []) if e.get("status") == "ok"}
    cap = max(200, min(int(cap), MAX_MATERIAL_CHARS))

    if dry_run:
        client = client or _DryClient(model=model)
    elif client is None:
        client = LlmClient(endpoint=endpoint, model=model, max_tokens=max_tokens,
                           api_key=load_api_key())
    kb = None if dry_run else KnowledgeStore(os.path.join(base, "knowledge.db"))
    stats = {"selected": len(targets), "called": 0, "cached": 0, "notes": 0,
             "errors": 0, "model": client.model, "dry_run": dry_run}
    try:
        for doc in targets:
            full_text = doc["meta"]["text"]
            tsha = _sha(full_text)
            key = "llm-enrich:%s:%s:%s" % (doc["id"], tsha[:16], client.model)
            if key in done_keys and not force:
                stats["cached"] += 1
                continue
            material = "材料路径：%s\n\n材料内容（截断至 %d 字符）：\n%s\n\n请按系统要求输出 JSON。" % (
                doc["file"], cap, full_text[:cap])
            entry = {"key": key, "doc": doc["file"], "text_sha": tsha,
                     "prompt_sha": _sha(SYSTEM_PROMPT + material)[:16]}
            if dry_run:
                entry.update({"status": "dry-run", "material_chars": min(len(full_text), cap)})
                audit.setdefault("entries", []).append(entry)
                stats["called"] += 1  # dry-run 记"将调用"数
                continue
            try:
                raw, usage = client.complete(SYSTEM_PROMPT, material)
                parsed = parse_llm_json(raw)
            except ValueError as error:
                entry.update({"status": "error", "error": "parse: %s" % error})
                audit.setdefault("entries", []).append(entry)
                stats["errors"] += 1
                continue
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                entry.update({"status": "error", "error": "transport: %s" % error})
                audit.setdefault("entries", []).append(entry)
                stats["errors"] += 1
                continue
            body, claims = build_note(client.model, doc, tsha, parsed)
            # force 重跑：模型输出可能不同，同一幂等键会触发内容冲突——用带后缀的新键
            # 生成新笔记（旧笔记保留，可用 withdraw/forget 清理）；普通模式严格幂等。
            submit_key = key if not force else "%s:force:%d" % (key, int(time.time() * 1000))
            result = kb.submit(body, claims, idempotency_key=submit_key)
            entry.update({"status": "ok", "note_id": result["note_id"],
                          "usage": usage, "summary_head": parsed["summary"][:80]})
            audit.setdefault("entries", []).append(entry)
            stats["called"] += 1
            stats["notes"] += 1
    finally:
        if kb is not None:
            kb.close()
    if not dry_run:
        audit["updated"] = time.time()
        with open(audit_path, "w", encoding="utf-8") as f:
            json.dump(audit, f, ensure_ascii=False, indent=1)
    return stats


class _DryClient:
    """dry-run 占位：携带真实模型名（保证缓存键一致），但绝不发起调用。"""

    def __init__(self, model=None):
        self.model = model or os.environ.get("DOMIMAP_LLM_MODEL") or DEFAULT_MODEL

    def complete(self, system, user):
        raise AssertionError("dry_run 不得发起调用")
