#!/usr/bin/env python3
"""四竞品主轨宿主：同一 GLM-5.3 循环 × 各自原生接口（工具提供者注入）。

- CbmMcpHost：cbm MCP stdio，会话期 tools/list 动态发现其原生工具（真原生接口）。
- CliToolHost：codegraph explore / graphify query / claude-obsidian retrieve 的原生命令
  包装为单工具；工作区副本与建库复用诊断轨适配器语义（同清单同预算）。
凭据纪律与 glm_host 相同：key 仅内存。
"""
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "benchmarks"))
sys.path.insert(0, ROOT)

from runners.glm_host import GlmApiHost, McpBridge, _post, load_api_key  # noqa: E402

COMP = os.path.expanduser("~/work/yingta/kb-tools-analysis/repos")


class CbmMcpHost(GlmApiHost):
    """cbm 原生 MCP：tools/list 动态发现，inputSchema→input_schema，全量暴露。"""

    name = "cbm-native-mcp"

    def __init__(self, repos, max_turns=6, transport=None, budget=None):
        self.repos = repos
        self.budget = dict({"prepare_timeout": 900, "query_timeout": 90}, **(budget or {}))
        super().__init__(graph_path=None, max_turns=max_turns, transport=transport)
        self._tools_cache = None

    def _spawn(self):
        binary = os.path.join(COMP, "codebase-memory-mcp", "build", "c",
                              "codebase-memory-mcp")
        proc = subprocess.Popen([binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, bufsize=1)
        return _JsonRpc(proc)

    def _ensure_indexed(self):
        """索引一次、工具表缓存一次（每题新会话=重置模型上下文，非重建索引——
        与诊断轨适配器同语义；重开进程重索引 7 仓 ×33 题不可承受）。"""
        if self._tools_cache is not None:
            return
        rpc = self._spawn()
        rpc.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                "clientInfo": {"name": "dm-maintrack", "version": "1"}})
        rpc.notify("notifications/initialized")
        for repo in self.repos:
            rpc.call("tools/call", {"name": "index_repository",
                                    "arguments": {"repo_path": os.path.abspath(repo.root)}},
                     timeout=self.budget.get("prepare_timeout"))
        tools = rpc.call("tools/list", {})
        self._tools_cache = [
            {"name": t["name"],
             "description": t.get("description", "")[:400],
             "input_schema": t.get("inputSchema") or {"type": "object"}}
            for t in tools.get("tools", []) if t["name"] != "index_repository"]
        self._rpc = rpc

    def open_session(self, registration):
        self._ensure_indexed()
        return {"id": "sess-%d" % int(time.time() * 1000), "registration": registration,
                "rpc": self._rpc}

    def close_session(self, session):
        return None  # 进程生命周期随宿主（close() 显式关闭）

    def close(self):
        rpc = getattr(self, "_rpc", None)
        if rpc:
            try:
                rpc.proc.stdin.close()
                rpc.proc.wait(timeout=10)
            except Exception:
                rpc.proc.kill()

    def _session_tools(self, session):
        return self._tools_cache

    def _session_exec(self, session, name, arguments):
        result = session["rpc"].call("tools/call", {"name": name, "arguments": arguments},
                                     timeout=self.budget.get("query_timeout"))
        if isinstance(result, dict):
            return "".join(c.get("text", "") for c in result.get("content", []))
        return str(result)


class _JsonRpc:
    def __init__(self, proc):
        self.proc = proc
        self.rid = 0

    def call(self, method, params=None, timeout=90.0):
        import select
        self.rid += 1
        msg = {"jsonrpc": "2.0", "method": method, "id": self.rid}
        if params:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        deadline = time.time() + float(timeout)
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError("cbm no response %.0fs: %s" % (timeout, method))
            ready, _, _ = select.select([self.proc.stdout], [], [], remaining)
            if not ready:
                raise TimeoutError("cbm no response %.0fs: %s" % (timeout, method))
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("cbm closed")
            data = json.loads(line)
            if data.get("id") == self.rid:
                if "error" in data:
                    raise RuntimeError("cbm error: %s" % json.dumps(data["error"])[:200])
                return data.get("result")

    def notify(self, method):
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.proc.stdin.flush()


class CliToolHost(GlmApiHost):
    """CLI 原生命令包装（codegraph explore / graphify query / obsidian retrieve）。
    工作区副本与建库在 prepare_done 由调用方完成后，仅暴露查询工具。"""

    def __init__(self, system_name, tool_name, tool_desc, exec_fn, repos,
                 max_turns=6, transport=None):
        self.system_name = system_name
        self.tool_name = tool_name
        self.tool_desc = tool_desc
        self.exec_fn = exec_fn
        self.repos = repos
        super().__init__(graph_path=None, max_turns=max_turns, transport=transport)

    @property
    def name(self):
        return self.system_name

    def open_session(self, registration):
        return {"id": "sess-%d" % int(time.time() * 1000), "registration": registration}

    def close_session(self, session):
        return None

    def _session_tools(self, session):
        return [{"name": self.tool_name, "description": self.tool_desc,
                 "input_schema": {"type": "object",
                                  "properties": {"query": {"type": "string"}},
                                  "required": ["query"]}}]

    def _session_exec(self, session, name, arguments):
        if name != self.tool_name:
            raise RuntimeError("unknown tool %s" % name)
        return self.exec_fn(str(arguments.get("query", "")))


def _patched_ask(self, session, question_text):
    """GlmApiHost.ask 的工具提供者版：tools spec / 执行来自会话注入。"""
    from runners.glm_host import SYSTEM_PROMPT, MODEL
    ledger = {"tool_calls": 0, "tokens_in": 0, "tokens_out": 0, "secs": 0.0}
    tools = self._session_tools(session)
    messages = [{"role": "user", "content": question_text}]
    answer = ""
    for _turn in range(self.max_turns):
        t0 = time.time()
        data = self._transport({
            "model": MODEL, "system": SYSTEM_PROMPT, "max_tokens": self.max_tokens,
            "messages": messages, "tools": tools})
        usage = data.get("usage", {})
        ledger["tokens_in"] += usage.get("input_tokens", 0)
        ledger["tokens_out"] += usage.get("output_tokens", 0)
        ledger["secs"] += time.time() - t0
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
                out = self._session_exec(session, tu["name"], tu.get("input", {}))
            except Exception as error:
                out = "工具错误：%s" % error
            results.append({"type": "tool_result", "tool_use_id": tu["id"],
                            "content": out[:6000]})
        messages.append({"role": "user", "content": results})
    if not answer:
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


# 工具提供者宿主的 ask 替换（不动 GlmApiHost 本体：domimap 宿主保持 McpBridge 专用路径）
for _cls in (CbmMcpHost, CliToolHost):
    _cls.ask = _patched_ask


def make_cli_exec(kind, workdir_by_repo):
    """codegraph/graphify/obsidian 的原生命令执行器（工作区副本已建库）。"""
    if kind == "codegraph":
        binary = os.path.join(COMP, "codegraph", "dist", "bin", "codegraph.js")

        def run(query):
            outs = []
            for d in workdir_by_repo.values():
                r = subprocess.run(["node", binary, "explore", query], cwd=d,
                                   capture_output=True, text=True, timeout=90)
                outs.append("# repo %s\n%s" % (os.path.basename(d), r.stdout[:4000]))
            return "\n\n".join(outs)[:12000]
        return run
    if kind == "graphify":
        venv = None
        if os.path.isfile("/tmp/dm-gf-venv.txt"):
            venv = open("/tmp/dm-gf-venv.txt").read().strip().split("=", 1)[-1]
        gf = os.path.join(venv or "", "bin", "graphify")

        def run(query):
            outs = []
            for d in workdir_by_repo.values():
                r = subprocess.run([gf, "query", query], cwd=d,
                                   capture_output=True, text=True, timeout=90)
                if r.returncode == 4 and "No matching nodes" in r.stdout:
                    outs.append("# repo %s：无匹配节点" % os.path.basename(d))
                elif r.returncode != 0:
                    outs.append("# repo %s：exit %d %s" % (os.path.basename(d),
                                                           r.returncode, r.stderr[:200]))
                else:
                    outs.append("# repo %s\n%s" % (os.path.basename(d), r.stdout[:4000]))
            return "\n\n".join(outs)[:12000]
        return run
    if kind == "obsidian":
        retr = os.path.join(COMP, "claude-obsidian", "scripts", "retrieve.py")

        def run(query):
            outs = []
            for vault in workdir_by_repo.values():
                r = subprocess.run(["python3", retr, "--vault", vault, query, "--no-rerank"],
                                   capture_output=True, text=True, timeout=120)
                if r.returncode != 0:
                    outs.append("# vault %s：exit %d" % (os.path.basename(vault), r.returncode))
                    continue
                try:
                    payload = json.loads(r.stdout[r.stdout.index("{"):])
                    cands = [c.get("page_path", "") for c in payload.get("candidates", [])][:8]
                    outs.append("# vault %s\n%s" % (os.path.basename(vault), "\n".join(cands)))
                except (ValueError, IndexError):
                    outs.append("# vault %s：非 JSON 输出" % os.path.basename(vault))
            return "\n\n".join(outs)[:12000]
        return run
    raise ValueError("unknown kind %r" % kind)


def prepare_cli_workspaces(kind, repos, base_dir, budget=None):
    """建工作区副本+索引（与诊断轨适配器同语义：截断记账、原生命令建库）。"""
    import shutil
    budget = budget or {"prepare_timeout": 420, "co_page_cap": 300}
    os.makedirs(base_dir, exist_ok=True)
    dirs = {}
    for repo in repos:
        d = os.path.join(base_dir, repo.name)
        if os.path.isdir(d):
            dirs[repo.name] = d
            continue
        if kind == "obsidian":
            from adapters.claude_obsidian_adapter import ClaudeObsidianAdapter
            adapter = ClaudeObsidianAdapter(os.path.join(base_dir, "_artifacts"))
            adapter._prepare_repo(repo, budget)
            # vault 路径在临时 workdir 内——改用持久 base_dir 重建
            import tempfile
            work = tempfile.mkdtemp(dir=base_dir, prefix="vault-")
            vault = os.path.join(work, repo.name)
            wiki = os.path.join(vault, "wiki", repo.name)
            os.makedirs(wiki, exist_ok=True)
            pages, oversize = [], []
            for dirpath, dirnames, filenames in os.walk(repo.root):
                dirnames[:] = [x for x in dirnames if x not in
                               {".git", "node_modules", "target", "build", "__pycache__"}]
                for fn in filenames:
                    src = os.path.join(dirpath, fn)
                    rel = os.path.relpath(src, repo.root)
                    try:
                        if os.path.getsize(src) >= 400000:
                            oversize.append(rel)
                            continue
                        shutil.copyfile(src, os.path.join(wiki, rel.replace("/", "__") + ".md"),
                                        follow_symlinks=False)
                        pages.append(rel)
                    except OSError:
                        pass
            cap = int(budget.get("co_page_cap", 300))
            pages.sort()
            for rel in pages[cap:]:
                os.remove(os.path.join(wiki, rel.replace("/", "__") + ".md"))
            r = subprocess.run(["bash", os.path.join(COMP, "claude-obsidian", "scripts",
                                                     "setup-retrieve.sh"),
                                "--vault", vault, "--apply"],
                               cwd=COMP, capture_output=True, text=True,
                               timeout=budget.get("prepare_timeout", 420))
            if r.returncode != 0:
                raise RuntimeError("setup-retrieve exit %d for %s" % (r.returncode, repo.name))
            dirs[repo.name] = vault
        else:
            shutil.copytree(repo.root, d, ignore_dangling_symlinks=True)
            if kind == "codegraph":
                binary = os.path.join(COMP, "codegraph", "dist", "bin", "codegraph.js")
                for args in (["init"], ["index", "."]):
                    r = subprocess.run(["node", binary, *args], cwd=d,
                                       capture_output=True, text=True,
                                       timeout=budget.get("prepare_timeout", 420))
                    if r.returncode != 0:
                        raise RuntimeError("codegraph %s exit %d" % (args, r.returncode))
            elif kind == "graphify":
                venv = open("/tmp/dm-gf-venv.txt").read().strip().split("=", 1)[-1]
                gf = os.path.join(venv, "bin", "graphify")
                r = subprocess.run([gf, "update", "."], cwd=d, capture_output=True,
                                   text=True, timeout=budget.get("prepare_timeout", 420))
                if r.returncode != 0:
                    raise RuntimeError("graphify update exit %d" % r.returncode)
            dirs[repo.name] = d
    return dirs
