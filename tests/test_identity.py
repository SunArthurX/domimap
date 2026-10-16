"""M1.1 身份与边界契约（AC-R01-01 / AC-R08-01）——先失败后实现的反例集。"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from domimap import lite_scan  # noqa: E402
from domimap.graph import Graph, load_seeds  # noqa: E402
from domimap.source import OutOfRootError, SourceRegistry  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "identity")

def merged(roots):
    R = None
    for p in roots:
        label = os.path.basename(p)
        one = lite_scan.scan_repo(p, repo_label=label)
        if R is None:
            R = one
            R["services"] = dict(one["services"])
            continue
        for k in ("classes", "methods", "routes", "rpc", "topics", "sqlstmts",
                  "tables", "pages", "docs", "entities", "calls"):
            R[k].extend(one[k])
        R["services"].update(one["services"])
        R["coverage"]["skipped"].extend(one["coverage"]["skipped"])
    return R

def build(roots):
    g = Graph()
    g.build_from_records(merged(roots), load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
    return g

class TestCrossRepoIdentity(unittest.TestCase):
    def test_same_fqn_and_same_path_doc_stay_separate(self):
        g = build([os.path.join(FIX, "repoA"), os.path.join(FIX, "repoB")])
        cls = [n for n in g.nodes.values() if n["kind"] == "Class" and n["name"] == "SameName"]
        self.assertEqual(len(cls), 2, "跨仓同 FQN 类必须独立：%s" % [c["id"] for c in cls])
        self.assertEqual({c["id"] for c in cls},
                         {"cls:repoA:com.example.shared.SameName", "cls:repoB:com.example.shared.SameName"})
        docs = [n for n in g.nodes.values() if n["kind"] == "Doc" and "README" in n["name"]]
        self.assertEqual(len(docs), 2, "同路径 README 必须按仓独立")
        texts = {d["meta"].get("text", "") for d in docs}
        self.assertIn("unique-alpha", "".join(texts))
        self.assertIn("unique-beta", "".join(texts))

    def test_root_order_swap_equivalent_ids(self):
        a = build([os.path.join(FIX, "repoA"), os.path.join(FIX, "repoB")])
        b = build([os.path.join(FIX, "repoB"), os.path.join(FIX, "repoA")])
        self.assertEqual(set(a.nodes), set(b.nodes), "ID 必须与根顺序无关")

class TestOutOfRoot(unittest.TestCase):
    def test_symlink_escape_rejected_and_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            secret = os.path.join(tmp, "secret.txt")
            with open(secret, "w", encoding="utf-8") as f:
                f.write("dm-out-of-root-marker-7741")
            link = os.path.join(FIX, "repoA", "escape.md")
            os.symlink(secret, link)
            try:
                g = build([os.path.join(FIX, "repoA")])
                blob = json.dumps([n for n in g.nodes.values()], ensure_ascii=False)
                self.assertNotIn("dm-out-of-root-marker-7741", blob, "越界内容不得入图")
                R = merged([os.path.join(FIX, "repoA")])
                self.assertTrue(any("越界" in s.get("reason", "") for s in R["coverage"]["skipped"]),
                                "越界拒绝必须显式记录：%s" % R["coverage"]["skipped"])
            finally:
                os.remove(link)

    def test_registry_rejects_paths_outside_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = SourceRegistry(os.path.join(tmp, "root"))
            os.makedirs(reg.root, exist_ok=True)
            with open(os.path.join(tmp, "outside.txt"), "w", encoding="utf-8") as f:
                f.write("x")
            with self.assertRaises(OutOfRootError):
                reg.register("repoX", os.path.join(tmp, "outside.txt"))

class TestSourceRegistry(unittest.TestCase):
    def test_register_hash_and_roundtrip_stable_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = SourceRegistry(os.path.join(tmp, "root"))
            repo = os.path.join(reg.root, "repoA")
            os.makedirs(os.path.join(repo, "src"), exist_ok=True)
            f1 = os.path.join(repo, "src", "a.txt")
            with open(f1, "wb") as f:
                f.write(b"hello")
            rid = reg.register_root(repo, label="repoA")
            s = reg.register(rid, f1)
            self.assertEqual(s.sha256, __import__("hashlib").sha256(b"hello").hexdigest())
            db = os.path.join(tmp, "sources.json")
            reg.save(db)
            reg2 = SourceRegistry.load(db)
            self.assertIn(s.sid, reg2.sources)
            self.assertEqual(reg2.sources[s.sid].sha256, s.sha256, "逻辑 ID 与内容版本必须稳定")
            self.assertNotEqual(reg2.sources[s.sid].repo, "", "登记必须绑定 repo")

class TestRebind(unittest.TestCase):
    def test_move_then_rebind_keeps_logical_identity(self):
        import hashlib as _h
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "root")
            repo = os.path.join(base, "repoA")
            os.makedirs(repo, exist_ok=True)
            f1 = os.path.join(repo, "a.txt")
            with open(f1, "wb") as f:
                f.write(b"payload")
            reg = SourceRegistry(base)
            rid = reg.register_root(repo, label="repoA")
            s = reg.register(rid, f1)
            db = os.path.join(tmp, "sources.json")
            reg.save(db)
            # 知识库/来源根移动
            moved = os.path.join(tmp, "root-moved")
            os.rename(base, moved)
            reg2 = SourceRegistry.load(db)
            with self.assertRaises(OutOfRootError):
                reg2.register(rid, os.path.join(moved, "repoA", "a.txt"), )  # 未重绑：拒绝并提示
            reg2.rebind(rid, os.path.join(moved, "repoA"))
            reg2.root = os.path.realpath(moved)  # 库根随迁（登记根=库根的场景）
            s2 = reg2.register(rid, os.path.join(moved, "repoA", "a.txt"))
            self.assertEqual(s2.sid, s.sid, "重绑后逻辑身份不变（AC-R01-02）")
            self.assertEqual(s2.sha256, s.sha256)


if __name__ == "__main__":
    unittest.main()
