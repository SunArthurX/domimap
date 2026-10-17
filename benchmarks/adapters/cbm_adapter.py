"""Codebase-Memory-MCP 适配器：MCP stdio JSON-RPC（index_repository full + search_graph）。

错误分类：JSON-RPC error / 进程退出 → 异常上抛（base 记 product_error 或逐仓失败）；
正则抽取的路径逐 token 验证存在性，无法映射的计数入 notes（不猜）。
"""
import json
import os
import re
import subprocess
import time

from .base import Adapter, map_to_repo
from . import envs

_TOKEN = re.compile(r"[\w./\\-]+\.[A-Za-z]{1,4}")


class CbmAdapter(Adapter):
    name = "codebase_memory_mcp"

    def __init__(self, artifact_dir, env=None):
        super().__init__(artifact_dir)
        self.env = env or envs.cbm_env()
        if not self.env["available"]:
            raise EnvironmentError("cbm binary unavailable: %s" % self.env.get("reason"))
        self.proc = None
        self.rid = 0
        self.project = {}

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
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("cbm process closed")
            data = json.loads(line)
            if data.get("id") == self.rid:
                if "error" in data:
                    raise RuntimeError("jsonrpc error: %s" % json.dumps(data["error"])[:300])
                return data.get("result")

    def _prepare_repo(self, repo, budget):
        if self.proc is None:
            self.proc = subprocess.Popen(
                [self.env["path"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, bufsize=1)
            self._call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                      "clientInfo": {"name": "dm-adapters", "version": "1"}})
            self._call("notifications/initialized", notify=True)
        result = self._call("tools/call", {"name": "index_repository",
                                           "arguments": {"repo_path": os.path.abspath(repo.root)}})
        payload = json.loads(result["content"][0]["text"])
        self.project[repo.name] = payload.get("project")
        return {"mode": "full(默认)", "project": payload.get("project"),
                "version_evidence": self.env.get("version_evidence")}

    def _query_repo(self, repo, text, budget):
        deadline = time.time() + float(budget.get("query_timeout", 60))
        if time.time() >= deadline:
            raise TimeoutError("cbm query budget exhausted before dispatch")
        result = self._call("tools/call", {"name": "search_graph",
                                           "arguments": {"query": text,
                                                         "project": self.project[repo.name]}})
        if time.time() > deadline:
            raise TimeoutError("cbm query exceeded budget")
        out = ""
        if isinstance(result, dict):
            out = "".join(c.get("text", "") for c in result.get("content", []))
        paths, notes = [], []
        unmapped = 0
        for token in _TOKEN.findall(out):
            candidate = token.replace("\\", "/")
            if os.path.isabs(candidate):
                mapped = map_to_repo(candidate, repo)
                if mapped == candidate:  # 绝对路径不属于该仓
                    unmapped += 1
                    continue
            elif os.path.exists(os.path.join(repo.root, candidate)):
                mapped = repo.name + "/" + candidate
            elif candidate.startswith(repo.name + "/") and \
                    os.path.exists(os.path.join(repo.root, candidate[len(repo.name) + 1:])):
                mapped = candidate
            else:
                unmapped += 1
                continue
            if mapped not in paths:
                paths.append(mapped)
        if unmapped:
            notes.append("unmapped_tokens=%d" % unmapped)
        return paths, notes

    def close_repo(self, repo):
        if self.proc is not None:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=10)
            except Exception:
                self.proc.kill()
            self.proc = None
        return None
