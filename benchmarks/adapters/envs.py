"""四竞品环境探测：入口存在性 + 版本证据。

探测失败 = SKIP（比较未完成），绝不当作产品失败或零分（specs/benchmark.md §2）。
"""
import os
import subprocess

COMP_ROOT = os.path.expanduser("~/work/yingta/kb-tools-analysis/repos")
GF_VENV_HINT = "/tmp/dm-gf-venv.txt"


def _probe(desc, path):
    return {"available": os.path.exists(path), "path": path, "what": desc}


def cbm_env():
    binary = os.path.join(COMP_ROOT, "codebase-memory-mcp", "build", "c", "codebase-memory-mcp")
    env = _probe("cbm 二进制（Makefile.cbm 构建）", binary)
    if env["available"]:
        env["version_evidence"] = "build/c 二进制 %d bytes" % os.path.getsize(binary)
    else:
        env["reason"] = "binary not built"
    return env


def codegraph_env():
    binary = os.path.join(COMP_ROOT, "codegraph", "dist", "bin", "codegraph.js")
    env = _probe("codegraph dist/bin/codegraph.js", binary)
    env["node"] = os.environ.get("PATH", "")
    if env["available"]:
        try:
            out = subprocess.run(["node", binary, "--version"], capture_output=True,
                                 text=True, timeout=30)
            env["version_evidence"] = out.stdout.strip() or out.stderr.strip()
        except Exception as error:
            env["available"] = False
            env["reason"] = "node run failed: %s" % error
    else:
        env["reason"] = "dist not built (npm run build)"
    return env


def graphify_env():
    env = {"available": False, "what": "graphify venv CLI"}
    candidates = []
    if os.path.isfile(GF_VENV_HINT):
        try:
            hinted = open(GF_VENV_HINT).read().strip().split("=", 1)[-1]
            candidates.append(hinted)
        except OSError:
            pass
    import tempfile
    for base in (tempfile.gettempdir(),):
        candidates.append(os.path.join(base, "dm-gf-venv"))
    for venv in candidates:
        bin_ = os.path.join(venv, "bin", "graphify")
        if os.path.exists(bin_):
            try:
                out = subprocess.run([bin_, "--version"], capture_output=True, text=True, timeout=30)
                env.update({"available": True, "path": bin_, "venv": venv,
                            "version_evidence": out.stdout.strip() or out.stderr.strip()})
                return env
            except Exception as error:
                env["reason"] = "graphify --version failed: %s" % error
    env["reason"] = "graphify venv not found (hint: %s)" % GF_VENV_HINT
    return env


def claude_obsidian_env():
    repo = os.path.join(COMP_ROOT, "claude-obsidian")
    env = _probe("claude-obsidian 克隆", repo)
    if env["available"]:
        try:
            probe = subprocess.run(
                ["python3", "-c",
                 "import sys; sys.path.insert(0, %r); import claude_obsidian as c;"
                 "print(c.__version__)" % repo],
                capture_output=True, text=True, timeout=60)
            if probe.returncode == 0:
                env["version_evidence"] = probe.stdout.strip()
            else:
                env["available"] = False
                env["reason"] = "import failed: %s" % probe.stderr.strip()[:200]
        except Exception as error:
            env["available"] = False
            env["reason"] = str(error)[:200]
    else:
        env["reason"] = "clone missing"
    return env


def all_envs():
    return {"codebase_memory_mcp": cbm_env(), "codegraph": codegraph_env(),
            "graphify": graphify_env(), "claude_obsidian": claude_obsidian_env()}


def json_dump():
    import json
    return json.dumps(all_envs(), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    print(json_dump())
