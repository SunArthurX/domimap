#!/usr/bin/env python3
"""真实主轨宿主：GLM-5.3（ZCode coding-plan key，用户授权）× domimap MCP 工具。

凭据纪律：key 位于 ~/.zcode/v2/credentials.json 的 enc:v1:AES-256-GCM 条目
（分段序 nonce/密文/tag，urlsafe-b64；密钥=sha256(env ZCODE_CREDENTIAL_SECRET 或
REDACTED-KDF-PREFIX:{platform}:{homedir}:{username})——KDF 取自 ZCode app
代码实证）。只在进程内存解密使用，绝不写入文件/日志/工件。
"""
import base64
import getpass
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENDPOINT = "https://open.bigmodel.cn/api/anthropic/v1/messages"
MODEL = "glm-5.3"
KEY_ENTRY = ("account-provider:coding-plan:account:"
             "REDACTED-KEY-ENTRY")

SYSTEM_PROMPT = (
    "你是知识库检索助手。使用提供的知识图工具回答用户问题。要求："
    "先检索再回答；结论必须给出处（文件路径/证据）；最多列 5 条主要证据；"
    "无法确认的部分明确说明；没有足够证据时如实回答不可确定，不要编造。")

TOOLS_SPEC = [
    {"name": "kg_explore",
     "description": "知识中台主检索：词法种子+图扩展，返回相关服务/类/方法/路由/表/"
                    "MQ主题/文档及关系（带置信与出处）",
     "input_schema": {"type": "object",
                      "properties": {"query": {"type": "string"},
                                     "domain": {"type": "string"},
                                     "top_k": {"type": "integer", "default": 6}},
                      "required": ["query"]}},
    {"name": "kg_read",
     "description": "按证据 ID 读固化片段（源修改/删除后仍为旧版本）",
     "input_schema": {"type": "object",
                      "properties": {"ev_id": {"type": "string"}},
                      "required": ["ev_id"]}},
]


def load_api_key():
    """内存解密 coding-plan api-key。永不落盘/打印。"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    path = os.path.expanduser("~/.zcode/v2/credentials.json")
    enc = json.load(open(path, encoding="utf-8"))[KEY_ENTRY]
    parts = enc[len("enc:v1:"):].split(".")

    def b64u(s):
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

    secret = os.environ.get("ZCODE_CREDENTIAL_SECRET") or (
        "REDACTED-KDF-PREFIX:%s:%s:%s" % (sys.platform,
                                                os.path.expanduser("~"),
                                                getpass.getuser()))
    key = hashlib.sha256(secret.encode()).digest()
    return AESGCM(key).decrypt(b64u(parts[0]), b64u(parts[2]) + b64u(parts[1]),
                               None).decode()


def _post(key, payload, timeout=180, retries=3):
    """瞬时网络故障有界重试（计划 §5.6：统一重试政策；实测单次 SSL 读超时曾中断整批）。"""
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(
            ENDPOINT, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "x-api-key": key,
                     "anthropic-version": "2023-06-01"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last = error
            if attempt + 1 < retries:
                time.sleep(5 * (attempt + 1))
    raise last


class McpBridge:
    """domimap MCP stdio 会话（每题一个 = 新会话语义）。"""

    def __init__(self, graph_path):
        self.proc = subprocess.Popen(
            [sys.executable, "-B", "-m", "domimap", "serve", "-g", graph_path],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1, cwd=ROOT)
        self.rid = 0

    def _call(self, method, params=None, notify=False):
        self.rid += 1
        msg = {"jsonrpc": "2.0", "method": method}
        if params:
            msg["params"] = params
        if not notify:
            msg["id"] = self.rid
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        if notify:
            return None
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("domimap serve closed")
        data = json.loads(line)
        if data.get("id") != self.rid:
            return self._call(method, params, notify)  # 跳过通知行
        if "error" in data:
            raise RuntimeError("mcp error: %s" % json.dumps(data["error"])[:200])
        return data.get("result")

    def start(self):
        self._call("initialize", {"protocolVersion": "2024-11-05",
                                  "capabilities": {},
                                  "clientInfo": {"name": "dm-maintrack", "version": "1"}})
        self._call("notifications/initialized", notify=True)

    def tool(self, name, arguments):
        result = self._call("tools/call", {"name": name, "arguments": arguments})
        if isinstance(result, dict):
            return "".join(c.get("text", "") for c in result.get("content", []))
        return str(result)

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


class GlmApiHost:
    """HostAdapter 形态的真实宿主：ask() 内部跑完整工具调用循环。"""

    name = "zcode-glm-anthropic"
    model = MODEL
    synthetic = False

    def __init__(self, graph_path, max_turns=6, transport=None, bridge_factory=None,
                 max_tokens=4096):
        self.graph_path = graph_path
        self.max_turns = max_turns
        self.max_tokens = max_tokens  # GLM-5.3 为推理模型：thinking 块先耗小额度，2048 会截断终答
        self._transport = transport or (lambda payload: _post(load_api_key(), payload))
        self._bridge_factory = bridge_factory or (lambda: _BridgeWrapper(McpBridge(graph_path)))

    def open_session(self, registration):
        bridge = self._bridge_factory()
        bridge.start()
        return {"id": "sess-%d" % int(time.time() * 1000), "registration": registration,
                "bridge": bridge}

    def close_session(self, session):
        session["bridge"].close()

    def ask(self, session, question_text):
        ledger = {"tool_calls": 0, "tokens_in": 0, "tokens_out": 0, "secs": 0.0}
        messages = [{"role": "user", "content": question_text}]
        answer = ""
        for _turn in range(self.max_turns):
            t0 = time.time()
            data = self._transport({
                "model": MODEL, "system": SYSTEM_PROMPT, "max_tokens": self.max_tokens,
                "messages": messages, "tools": TOOLS_SPEC})
            usage = data.get("usage", {})
            ledger["tokens_in"] += usage.get("input_tokens", 0)
            ledger["tokens_out"] += usage.get("output_tokens", 0)
            ledger["secs"] += time.time() - t0
            # anthropic 响应 content 在顶层；测试桩可用 message.content 嵌套（两者兼容）
            blocks = data.get("content") or (data.get("message") or {}).get("content") or []
            texts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
            tool_uses = [b for b in blocks if b.get("type") == "tool_use"]
            if not tool_uses:
                answer = "\n".join(t for t in texts if t)
                break
            messages.append({"role": "assistant", "content": blocks})
            results = []
            for tu in tool_uses:
                ledger["tool_calls"] += 1
                try:
                    out = session["bridge"].tool(tu["name"], tu.get("input", {}))
                except Exception as error:  # 工具失败如实回填，不吞
                    out = "工具错误：%s" % error
                results.append({"type": "tool_result",
                                "tool_use_id": tu["id"],
                                "content": out[:6000]})
            messages.append({"role": "user", "content": results})
        if not answer:
            # 兜底终答：轮次耗尽仍无文本（实测 12/33 题六轮全耗在工具循环）——
            # 去掉 tools 强制作答一次，保证题有答案（预算内、不静默）
            t0 = time.time()
            data = self._transport({
                "model": MODEL, "system": SYSTEM_PROMPT, "max_tokens": self.max_tokens,
                "messages": messages + [{"role": "user",
                                         "content": "检索阶段结束。请基于以上检索结果直接作答；"
                                                    "每个结论标注来源文件路径；证据不足处如实说明。"}]})
            usage = data.get("usage", {})
            ledger["tokens_in"] += usage.get("input_tokens", 0)
            ledger["tokens_out"] += usage.get("output_tokens", 0)
            ledger["secs"] += time.time() - t0
            blocks = data.get("content") or (data.get("message") or {}).get("content") or []
            answer = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return {"answer_text": answer, "tool_calls": ledger["tool_calls"],
                "tokens_in": ledger["tokens_in"], "tokens_out": ledger["tokens_out"],
                "secs": round(ledger["secs"], 3), "ledger": ledger}


class _BridgeWrapper:
    def __init__(self, bridge):
        self.bridge = bridge

    def start(self):
        self.bridge.start()

    def tool(self, name, arguments):
        return self.bridge.tool(name, arguments)

    def close(self):
        self.bridge.close()
