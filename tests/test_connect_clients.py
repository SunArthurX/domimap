"""F1-C1..C4 接入自动化：四客户端原生配置的生成、幂等接入、受管撤销与诊断（domimap connect/disconnect/clients）。

此前（漂移审计 §3 F1 行、M4 矩阵）：无任何 connect 类命令；四客户端均手工登记一次、无版本化模板、无幂等撤销脚本。
本片不声称真实会话验收（AC-F1-C*-01/02 仍需真实客户端新会话），只保证配置动作可重复、可撤销、不碰其它条目。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from domimap import clients

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


class TestConnectClients(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dm-connect-")
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name
        os.makedirs(os.path.join(self.home, "ws"))
        self.graph = os.path.join(self.home, "ws", "graph.json")
        open(self.graph, "w").write('{"nodes": [], "edges": [], "schema": "domimap.lite.v1"}')
        self.py = "/opt/py/bin/python3"

    def _connect(self, client, **kw):
        kw.setdefault("home", self.home); kw.setdefault("python", self.py); kw.setdefault("repo_root", "/repo/domimap")
        return clients.connect(client, self.graph, **kw)

    # ---------- JSON 客户端（Claude / ZCode） ----------
    def test_json_clients_add_idempotent_preserve_others_and_remove_managed_only(self):
        for client, rel in (("claude", ".claude.json"), ("zcode", ".zcode/mcp.json")):
            path = os.path.join(self.home, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            json.dump({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}, open(path, "w"))
            r = self._connect(client)
            self.assertEqual(r["action"], "added", r)
            self.assertTrue(r["backup"] and os.path.exists(r["backup"]), "写前备份")
            d = json.load(open(path))
            self.assertEqual(d["theme"], "dark"); self.assertIn("other", d["mcpServers"])
            entry = d["mcpServers"]["domimap"]
            self.assertEqual(entry["command"], self.py)
            self.assertEqual(entry["args"], ["-B", "-m", "domimap", "serve", "-g", self.graph])
            self.assertEqual(entry["env"], {"PYTHONPATH": "/repo/domimap"})
            r2 = self._connect(client)
            self.assertEqual(r2["action"], "unchanged")
            self.assertEqual(len([p for p in os.listdir(os.path.dirname(path)) if ".dm-backup" in p]), 1, "幂等：不重复备份")
            st = clients.status(client, home=self.home)
            self.assertTrue(st["present"] and st["managed"] and st["graph_exists"])
            rm = clients.disconnect(client, home=self.home)
            self.assertTrue(rm["removed"])
            d = json.load(open(path))
            self.assertNotIn("domimap", d["mcpServers"]); self.assertIn("other", d["mcpServers"]); self.assertEqual(d["theme"], "dark")
            self.assertFalse(clients.disconnect(client, home=self.home)["removed"], "再次撤销无事")

    def test_enable_write_flag_is_passed_through(self):
        r = self._connect("claude", enable_write=True)
        d = json.load(open(os.path.join(self.home, ".claude.json")))
        self.assertIn("--enable-write", d["mcpServers"]["domimap"]["args"])

    # ---------- Codex TOML ----------
    def test_codex_toml_block_added_and_removed_without_touching_others(self):
        path = os.path.join(self.home, ".codex", "config.toml")
        os.makedirs(os.path.dirname(path))
        open(path, "w").write('model = "gpt-x"\n\n[mcp_servers.node_repl]\nargs = []\ncommand = "/bin/node_repl"\n\n[mcp_servers.node_repl.env]\nA = "1"\n')
        r = self._connect("codex")
        self.assertEqual(r["action"], "added")
        text = open(path).read()
        self.assertIn("[mcp_servers.domimap]", text)
        self.assertIn('command = "%s"' % self.py, text)
        self.assertIn('args = ["-B", "-m", "domimap", "serve", "-g", "%s"]' % self.graph, text)
        self.assertIn("[mcp_servers.domimap.env]\nPYTHONPATH = \"/repo/domimap\"", text)
        self.assertIn("[mcp_servers.node_repl]", text); self.assertIn('model = "gpt-x"', text)
        if sys.version_info >= (3, 11):
            import tomllib
            d = tomllib.loads(text)
            self.assertEqual(d["mcp_servers"]["domimap"]["args"][-1], self.graph)
            self.assertEqual(d["mcp_servers"]["node_repl"]["env"]["A"], "1")
        self.assertEqual(self._connect("codex")["action"], "unchanged")
        self.assertEqual(text, open(path).read(), "幂等：文件不变")
        self.assertTrue(clients.disconnect("codex", home=self.home)["removed"])
        text2 = open(path).read()
        self.assertNotIn("domimap", text2); self.assertIn("[mcp_servers.node_repl.env]\nA = \"1\"", text2)

    # ---------- DSH cordis.patch.yml ----------
    def test_dsh_row_inserted_under_insert_list_and_removed(self):
        path = os.path.join(self.home, ".dsh", "cordis.patch.yml")
        os.makedirs(os.path.dirname(path))
        open(path, "w").write("# overlay\n- insert:\n    - id: crm\n      name: '@deepseek-ai/dsh-crm'\n      config:\n        riskProfileValidityDays: 730\n")
        r = self._connect("dsh")
        self.assertEqual(r["action"], "added")
        text = open(path).read()
        self.assertIn("    - id: mcp-domimap\n      name: '@deepseek-ai/dsh-mcp-client'\n      config:\n        serverName: domimap\n        transport: stdio\n", text)
        self.assertIn("        command: %s\n" % self.py, text)
        self.assertIn("        args: ['-B', '-m', 'domimap', 'serve', '-g', '%s']\n" % self.graph, text)
        self.assertIn("          PYTHONPATH: /repo/domimap\n", text)
        self.assertIn("    - id: crm\n", text)
        self.assertEqual(self._connect("dsh")["action"], "unchanged")
        self.assertEqual(text.count("mcp-domimap"), 1)
        self.assertTrue(clients.disconnect("dsh", home=self.home)["removed"])
        text2 = open(path).read()
        self.assertNotIn("mcp-domimap", text2); self.assertIn("riskProfileValidityDays: 730", text2)

    def test_dsh_creates_patch_file_when_absent(self):
        r = self._connect("dsh")
        self.assertEqual(r["action"], "added")
        text = open(os.path.join(self.home, ".dsh", "cordis.patch.yml")).read()
        self.assertTrue(text.lstrip("#\n ").startswith("- insert:") or "- insert:" in text)
        self.assertIn("mcp-domimap", text)

    # ---------- 受管边界 ----------
    def test_user_authored_entry_is_not_overwritten_without_force(self):
        path = os.path.join(self.home, ".claude.json")
        json.dump({"mcpServers": {"domimap": {"command": "my-own", "args": []}}}, open(path, "w"))
        with self.assertRaises(clients.ManagedConflict):
            self._connect("claude")
        self.assertEqual(json.load(open(path))["mcpServers"]["domimap"]["command"], "my-own", "未 force 不得覆盖")
        r = self._connect("claude", force=True)
        self.assertEqual(r["action"], "replaced")
        self.assertEqual(json.load(open(path))["mcpServers"]["domimap"]["command"], self.py)
        # 用户事后手改 → 受管撤销拒绝（非 force）
        d = json.load(open(path)); d["mcpServers"]["domimap"]["args"].append("--extra"); json.dump(d, open(path, "w"))
        with self.assertRaises(clients.ManagedConflict):
            clients.disconnect("claude", home=self.home)
        self.assertTrue(clients.disconnect("claude", home=self.home, force=True)["removed"])

    def test_dry_run_writes_nothing_and_renders_snippet(self):
        for client in ("claude", "codex", "zcode", "dsh"):
            r = self._connect(client, dry_run=True)
            self.assertEqual(r["action"], "dry-run")
            self.assertIn("domimap", r["snippet"])
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude.json")))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".codex")))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".domimap", "connect.json")))

    def test_unknown_client_and_missing_graph_rejected(self):
        with self.assertRaises(ValueError):
            self._connect("cursor")
        with self.assertRaises(FileNotFoundError):
            clients.connect("claude", os.path.join(self.home, "nope.json"), home=self.home, python=self.py)

    def test_cli_connect_clients_disconnect(self):
        env = dict(os.environ, HOME=self.home)
        run = lambda *a: subprocess.run([sys.executable, "-B", "-m", "domimap", *a], cwd=ROOT, env=env,
                                        capture_output=True, text=True)
        p = run("connect", "zcode", "-g", self.graph, "--python", self.py)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("added", p.stdout)
        p = run("clients")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("zcode", p.stdout); self.assertIn("present", p.stdout)
        self.assertIn("未验收", p.stdout, "真实会话验收状态如实标注，不因配置成功而勾完成")
        p = run("connect", "cursor", "-g", self.graph)
        self.assertEqual(p.returncode, 2)
        p = run("disconnect", "zcode")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("domimap", json.load(open(os.path.join(self.home, ".zcode", "mcp.json")))["mcpServers"])


if __name__ == "__main__":
    unittest.main()
