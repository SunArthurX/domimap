"""clients — F1：四客户端原生配置的生成、幂等接入、受管撤销与诊断（domimap connect / disconnect / clients）。

每个客户端用其**真实原生接口**（2026-10 本机实测，见 docs/clients.md），不套用别家配置：
- claude: ~/.claude.json            JSON  mcpServers.domimap
- codex:  ~/.codex/config.toml      TOML  [mcp_servers.domimap] (+ [mcp_servers.domimap.env])
- zcode:  ~/.zcode/mcp.json         JSON  mcpServers.domimap
- dsh:    ~/.dsh/cordis.patch.yml   YAML  `- insert:` 列表下的 `- id: mcp-domimap`（@deepseek-ai/dsh-mcp-client）

受管原则：只增删名为 domimap / mcp-domimap 的条目；写前备份（<配置>.dm-backup-<ts>）；条目与登记
（~/.domimap/connect.json）不一致且非本工具写入 → 不覆盖/不删除（需 --force）。
本模块让配置动作可重复、可撤销；**真实会话验收（AC-F1-C*-01/02）仍需在真实客户端新会话中进行**。
"""
import hashlib
import json
import os
import sys
import time

TEMPLATE_VERSION = "connect.v1"
SERVER_NAME = "domimap"
DSH_ROW_ID = "mcp-domimap"

CLIENTS = {
    "claude": {"product": "Claude Code", "config": ".claude.json", "format": "json",
               "verified_version": "2.1.296 (2026-10-16 本机)"},
    "codex": {"product": "Codex CLI", "config": os.path.join(".codex", "config.toml"), "format": "toml",
              "verified_version": "codex-cli 0.148.0 (2026-10-16 本机)"},
    "zcode": {"product": "ZCode", "config": os.path.join(".zcode", "mcp.json"), "format": "json",
              "verified_version": "ZCode.app 3.15.3 (2026-10-16 本机)"},
    "dsh": {"product": "DSH Code Agent (deepseek-harness)", "config": os.path.join(".dsh", "cordis.patch.yml"),
            "format": "dsh-yaml", "verified_version": "@deepseek-ai/dsh 0.1.2-alpha.1 (2026-10 本机)"},
}


class ManagedConflict(RuntimeError):
    """目标条目存在但不是本工具写入（或写入后被手改）：不静默覆盖/删除。"""


# ---------------------------------------------------------------- 条目
def _repo_root_if_source():
    """从源码检出运行（非 pip 安装）时，客户端拉起的子进程需要 PYTHONPATH 才能 import domimap。"""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    return root if os.path.exists(os.path.join(root, "pyproject.toml")) else None


def server_entry(graph_path, python=None, enable_write=False, repo_root=None):
    graph_path = os.path.abspath(graph_path)
    args = ["-B", "-m", "domimap", "serve", "-g", graph_path] + (["--enable-write"] if enable_write else [])
    entry = {"command": python or sys.executable, "args": args}
    root = _repo_root_if_source() if repo_root is None else repo_root
    if root:
        entry["env"] = {"PYTHONPATH": root}
    return entry


def _entry_sha(entry):
    return hashlib.sha256(json.dumps(entry, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _home(home):
    return os.path.abspath(home or os.path.expanduser("~"))


def _config_path(client, home):
    if client not in CLIENTS:
        raise ValueError("未知客户端：%s（可选 %s）" % (client, "/".join(sorted(CLIENTS))))
    return os.path.join(_home(home), CLIENTS[client]["config"])


# ---------------------------------------------------------------- 登记（谁写了什么）
def _registry_path(home):
    return os.path.join(_home(home), ".domimap", "connect.json")


def _registry_load(home):
    p = _registry_path(home)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _registry_save(home, data):
    p = _registry_path(home)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _backup(path):
    if not os.path.exists(path):
        return None
    bk = "%s.dm-backup-%d" % (path, int(time.time() * 1000))
    with open(path, "rb") as src, open(bk, "wb") as dst:
        dst.write(src.read())
    return bk


def _write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


# ---------------------------------------------------------------- JSON（claude / zcode）
def _json_read(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return json.loads(text) if text.strip() else {}


def _json_current(path):
    d = _json_read(path)
    return (d.get("mcpServers") or {}).get(SERVER_NAME)


def _json_write_entry(path, entry):
    d = _json_read(path)
    d.setdefault("mcpServers", {})[SERVER_NAME] = entry
    _write_text(path, json.dumps(d, ensure_ascii=False, indent=2) + "\n")


def _json_remove_entry(path):
    d = _json_read(path)
    if SERVER_NAME in (d.get("mcpServers") or {}):
        del d["mcpServers"][SERVER_NAME]
        _write_text(path, json.dumps(d, ensure_ascii=False, indent=2) + "\n")


def _json_render(entry):
    return json.dumps({"mcpServers": {SERVER_NAME: entry}}, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- TOML（codex）
def _toml_str(s):
    return json.dumps(s, ensure_ascii=False)  # JSON 字串字面量是合法 TOML 基本字串


def _toml_render(entry):
    lines = ["[mcp_servers.%s]" % SERVER_NAME,
             "command = %s" % _toml_str(entry["command"]),
             "args = [%s]" % ", ".join(_toml_str(a) for a in entry["args"])]
    if entry.get("env"):
        lines += ["", "[mcp_servers.%s.env]" % SERVER_NAME]
        lines += ["%s = %s" % (k, _toml_str(v)) for k, v in sorted(entry["env"].items())]
    return "\n".join(lines) + "\n"


def _toml_strip_blocks(text):
    """删除 [mcp_servers.domimap] 与 [mcp_servers.domimap.env] 两个表块（到下一个表头或文件尾）。"""
    out, skipping = [], False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("["):
            skipping = stripped in ("[mcp_servers.%s]" % SERVER_NAME, "[mcp_servers.%s.env]" % SERVER_NAME)
        if not skipping:
            out.append(line)
    result = "".join(out).rstrip("\n")
    return (result + "\n") if result else ""


def _toml_current(path):
    """解析我们管理的表块为 entry（只读自己写的键：command/args/env）。"""
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if sys.version_info >= (3, 11):
        import tomllib
        try:
            d = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return None
        return (d.get("mcp_servers") or {}).get(SERVER_NAME)
    # 3.9/3.10：按行读取本工具写出的简单形态
    entry, section = None, None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("["):
            section = s
            if section == "[mcp_servers.%s]" % SERVER_NAME:
                entry = entry or {}
            continue
        if section == "[mcp_servers.%s]" % SERVER_NAME and "=" in s:
            k, _, v = s.partition("=")
            entry[k.strip()] = json.loads(v.strip())
        elif section == "[mcp_servers.%s.env]" % SERVER_NAME and "=" in s:
            k, _, v = s.partition("=")
            entry.setdefault("env", {})[k.strip()] = json.loads(v.strip())
    return entry


def _toml_write_entry(path, entry):
    text = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            text = f.read()
    base = _toml_strip_blocks(text)
    new = (base + ("\n" if base and not base.endswith("\n\n") else "") + _toml_render(entry))
    if sys.version_info >= (3, 11):
        import tomllib
        tomllib.loads(new)  # 写前验证：合成结果必须是合法 TOML，否则不动原文件
    _write_text(path, new)


def _toml_remove_entry(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        text = f.read()
    _write_text(path, _toml_strip_blocks(text))


# ---------------------------------------------------------------- DSH YAML（cordis.patch.yml）
def _yaml_sq(s):
    return "'" + str(s).replace("'", "''") + "'"


def _dsh_render(entry):
    lines = ["    - id: %s" % DSH_ROW_ID,
             "      name: '@deepseek-ai/dsh-mcp-client'",
             "      config:",
             "        serverName: %s" % SERVER_NAME,
             "        transport: stdio",
             "        command: %s" % entry["command"],
             "        args: [%s]" % ", ".join(_yaml_sq(a) for a in entry["args"])]
    if entry.get("env"):
        lines.append("        env:")
        lines += ["          %s: %s" % (k, v) for k, v in sorted(entry["env"].items())]
    return "\n".join(lines) + "\n"


def _dsh_split(text):
    """返回 (前缀行, insert 列表行, 后缀行)：insert 列表 = `- insert:` 之后、下一个顶层项之前的行。"""
    lines = text.splitlines(keepends=True)
    start = next((i for i, l in enumerate(lines) if l.rstrip("\n") == "- insert:"), None)
    if start is None:
        return lines, None, []
    end = len(lines)
    for j in range(start + 1, len(lines)):
        l = lines[j]
        if l.strip() and not l.startswith(" ") and not l.startswith("#"):
            end = j
            break
    return lines[:start + 1], lines[start + 1:end], lines[end:]


def _dsh_strip_row(items):
    """从 insert 列表中删除 `- id: mcp-domimap` 块（到下一个同级 `    - id:` 或列表结束）。"""
    out, skipping = [], False
    for l in items:
        if l.startswith("    - "):
            skipping = l.strip() == "- id: %s" % DSH_ROW_ID
        if not skipping:
            out.append(l)
    return out


def _dsh_current(path):
    """从我们写出的行块中读回 entry（command/args/env）；块缺失返回 None。"""
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        text = f.read()
    _, items, _ = _dsh_split(text)
    if not items:
        return None
    block, inside = [], False
    for l in items:
        if l.startswith("    - "):
            inside = l.strip() == "- id: %s" % DSH_ROW_ID
            continue
        if inside:
            block.append(l.rstrip("\n"))
    if not block and not any(l.strip() == "- id: %s" % DSH_ROW_ID for l in items):
        return None
    entry, env = {}, {}
    for l in block:
        s = l.strip()
        if s.startswith("command:"):
            entry["command"] = s[len("command:"):].strip()
        elif s.startswith("args:"):
            raw = s[len("args:"):].strip()
            entry["args"] = json.loads(raw.replace("'", '"')) if raw.startswith("[") else []
        elif ":" in s and l.startswith("          "):
            k, _, v = s.partition(":")
            env[k.strip()] = v.strip()
    if env:
        entry["env"] = env
    return entry


def _dsh_write_entry(path, entry):
    text = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            text = f.read()
    prefix, items, suffix = _dsh_split(text)
    if items is None:
        head = (text if text.endswith("\n") or not text else text + "\n")
        new = head + ("" if head.endswith("\n\n") or not head else "\n") + "- insert:\n" + _dsh_render(entry)
    else:
        items = _dsh_strip_row(items)
        if items and not items[-1].endswith("\n"):
            items[-1] += "\n"
        new = "".join(prefix) + "".join(items) + ("\n" if items and items[-1].strip() else "") + _dsh_render(entry) + "".join(suffix)
    _write_text(path, new)


def _dsh_remove_entry(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        text = f.read()
    prefix, items, suffix = _dsh_split(text)
    if items is None:
        return
    _write_text(path, "".join(prefix) + "".join(_dsh_strip_row(items)) + "".join(suffix))


# ---------------------------------------------------------------- 分发
_IO = {
    "json": (_json_current, _json_write_entry, _json_remove_entry, _json_render),
    "toml": (_toml_current, _toml_write_entry, _toml_remove_entry, _toml_render),
    "dsh-yaml": (_dsh_current, _dsh_write_entry, _dsh_remove_entry, _dsh_render),
}


def render(client, entry):
    return _IO[CLIENTS[client]["format"]][3](entry)


def status(client, home=None):
    path = _config_path(client, home)
    current, _, _, _ = _IO[CLIENTS[client]["format"]]
    try:
        entry = current(path)
    except (ValueError, OSError):
        entry = None
    reg = _registry_load(home).get(client)
    graph = None
    if entry and "args" in entry and "-g" in entry["args"]:
        graph = entry["args"][entry["args"].index("-g") + 1]
    return {"client": client, "product": CLIENTS[client]["product"], "config": path,
            "config_exists": os.path.exists(path), "present": entry is not None,
            "managed": bool(entry is not None and reg and reg.get("entry_sha") == _entry_sha(entry)),
            "graph": graph, "graph_exists": bool(graph and os.path.exists(graph)),
            "command_exists": bool(entry and os.path.exists(entry.get("command", ""))),
            "template": reg.get("template") if reg else None,
            "verified_version": CLIENTS[client]["verified_version"],
            "session_acceptance": "未验收（AC-F1-%s 需真实客户端新会话记录）" % {"claude": "C1", "codex": "C2", "zcode": "C3", "dsh": "C4"}[client]}


def connect(client, graph_path, home=None, python=None, enable_write=False, repo_root=None,
            force=False, dry_run=False):
    """把 domimap serve 注册进客户端原生配置：added / replaced / unchanged / dry-run。"""
    path = _config_path(client, home)
    if not os.path.isfile(graph_path):
        raise FileNotFoundError("图文件不存在：%s（先 build）" % graph_path)
    entry = server_entry(graph_path, python=python, enable_write=enable_write, repo_root=repo_root)
    current, write, _, rend = _IO[CLIENTS[client]["format"]]
    if dry_run:
        return {"client": client, "config": path, "action": "dry-run", "snippet": rend(entry)}
    existing = current(path)
    reg = _registry_load(home)
    if existing is not None and _entry_sha(existing) == _entry_sha(entry):
        action = "unchanged"
        if reg.get(client, {}).get("entry_sha") != _entry_sha(entry):
            reg[client] = {"config": path, "entry_sha": _entry_sha(entry), "template": TEMPLATE_VERSION,
                           "written_at": time.time(), "backup": None}
            _registry_save(home, reg)
        return {"client": client, "config": path, "action": action, "backup": None}
    if existing is not None and not force:
        mine = reg.get(client, {}).get("entry_sha") == _entry_sha(existing)
        if not mine:
            raise ManagedConflict("%s 已有非本工具写入的 domimap 条目（%s）；确认后用 --force 覆盖" % (path, existing.get("command")))
    backup = _backup(path)
    write(path, entry)
    reg[client] = {"config": path, "entry_sha": _entry_sha(entry), "template": TEMPLATE_VERSION,
                   "written_at": time.time(), "backup": backup, "graph": os.path.abspath(graph_path)}
    _registry_save(home, reg)
    return {"client": client, "config": path, "action": "replaced" if existing is not None else "added",
            "backup": backup}


def disconnect(client, home=None, force=False):
    """受管撤销：只删 domimap 条目；条目被手改且非 force → 拒绝。"""
    path = _config_path(client, home)
    current, _, remove, _ = _IO[CLIENTS[client]["format"]]
    existing = current(path)
    reg = _registry_load(home)
    if existing is None:
        reg.pop(client, None)
        _registry_save(home, reg)
        return {"client": client, "config": path, "removed": False}
    mine = reg.get(client, {}).get("entry_sha") == _entry_sha(existing)
    if not mine and not force:
        raise ManagedConflict("%s 的 domimap 条目不是本工具写入或已被手改；确认后用 --force 删除" % path)
    backup = _backup(path)
    remove(path)
    reg.pop(client, None)
    _registry_save(home, reg)
    return {"client": client, "config": path, "removed": True, "backup": backup}
