"""D11 来源身份（R01）：身份不由 basename 推定；节点带来源身份；路径可重绑而逻辑身份不变。

AC-R01-01（跨仓同 basename/同相对路径不串接、顺序无关）、AC-R01-02（根移动后显式重绑，sid/节点 ID 稳定）。
"""
import json
import os
import shutil
import tempfile
import unittest

from domimap import batch
from domimap.graph import Graph, build as graph_build
from domimap.store import EvidenceStore, EvidenceResolver

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MINI = os.path.join(HERE, "fixtures", "mini")

JAVA = """package com.%(pkg)s.order;
import org.springframework.web.bind.annotation.*;
@RestController
public class OrderController {
    @PostMapping("/trade/price")
    public String changePrice(String id) { return %(ret)s; }
}
"""
MAPPER = """<?xml version="1.0"?>
<mapper namespace="com.%(pkg)s.order.OrderMapper">
  <update id="updatePrice">UPDATE t_order SET price=#{p} WHERE id=#{id}</update>
</mapper>
"""


def _make_repo(base, pkg, doc_text):
    """两个仓同名 svc/，各自不同包名与文档内容。"""
    root = os.path.join(base, pkg, "svc")
    os.makedirs(os.path.join(root, "order-service", "src", "com", pkg, "order"))
    os.makedirs(os.path.join(root, "order-service", "sqlmap"))
    os.makedirs(os.path.join(root, "docs"))
    open(os.path.join(root, "pom.xml"), "w").write("<project/>")
    with open(os.path.join(root, "order-service", "src", "com", pkg, "order", "OrderController.java"), "w") as f:
        f.write(JAVA % {"pkg": pkg, "ret": '"%s"' % pkg})
    with open(os.path.join(root, "order-service", "sqlmap", "OrderMapper.xml"), "w") as f:
        f.write(MAPPER % {"pkg": pkg})
    with open(os.path.join(root, "docs", "改价说明.md"), "w", encoding="utf-8") as f:
        f.write(doc_text)
    return root


class TestSourceIdentity(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dm-d11-")
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.ws = os.path.join(self.tmp, "ws")

    def _two_same_basename(self):
        a = _make_repo(self.tmp, "alpha", "# 改价说明\n\nalpha 仓：改价需走审批。\n")
        b = _make_repo(self.tmp, "beta", "# 改价说明\n\nbeta 仓：改价无需审批。\n")
        return a, b

    def test_same_basename_repos_keep_separate_identity(self):
        a, b = self._two_same_basename()
        g, _, results = batch.build_many([a, b], self.ws, force=True, merged_name="ws")
        labels = sorted(l for l, _ in results)
        self.assertEqual(len(set(labels)), 2, "同名仓必须得到不同标签：%s" % labels)
        self.assertTrue(all(l.startswith("svc") for l in labels))
        for l in labels:
            self.assertTrue(os.path.exists(os.path.join(self.ws, l, "manifest.json")), l)
        store = EvidenceStore(os.path.join(self.ws, "store.db"))
        self.addCleanup(store.close)
        sids = {r[0] for r in store.db.execute("SELECT sid FROM sources WHERE rel LIKE '%改价说明.md'")}
        self.assertEqual(len(sids), 2, "同相对路径的两份文档须各自固化：%s" % sids)
        docs = [n for n in g.nodes.values() if n["kind"] == "Doc" and n["file"].endswith("改价说明.md")]
        self.assertEqual(len(docs), 2, "同相对路径文档不得合并为一个节点")
        resolver = EvidenceResolver(store)
        texts = set()
        for d in docs:
            ev = resolver.for_node(d)
            self.assertIsNotNone(ev, "节点须能按来源身份解析证据：%s" % d["id"])
            rec = store.read_evidence(ev)
            self.assertTrue(rec["available"])
            texts.add(rec["text"])
        self.assertEqual(len(texts), 2, "两个同路径文档必须各读到自己的内容（不串接）")
        sql = [n["id"] for n in g.nodes.values() if n["kind"] == "SqlStmt"]
        self.assertEqual(len(sql), 2, "同 iface.id 的两仓 SQL 语句不得合并：%s" % sql)
        routes = [n["id"] for n in g.nodes.values() if n["kind"] == "Route"]
        self.assertEqual(len(routes), 2, "同路径路由不得跨仓合并：%s" % routes)

    def test_build_order_does_not_change_identity(self):
        a, b = self._two_same_basename()
        g1, _, _ = batch.build_many([a, b], os.path.join(self.tmp, "w1"), force=True)
        g2, _, _ = batch.build_many([b, a], os.path.join(self.tmp, "w2"), force=True)
        self.assertEqual(set(g1.nodes), set(g2.nodes), "身份不得依赖构建顺序")

    def test_nodes_carry_sid_and_ids_are_service_qualified(self):
        g, _ = graph_build(MINI, os.path.join(self.ws, "mini"))
        store = EvidenceStore(os.path.join(self.ws, "mini", "store.db"))
        self.addCleanup(store.close)
        backed = [n for n in g.nodes.values()
                  if n["kind"] in {"Class", "Method", "Route", "SqlStmt", "Page", "Doc"}]
        self.assertTrue(backed)
        for n in backed:
            self.assertIn("sid", n["meta"], "文件背书节点须带来源身份：%s" % n["id"])
            self.assertTrue(n["meta"]["sid"].endswith("|" + n["file"]), n["meta"]["sid"])
        by_sid = store.evidence_by_sid()
        self.assertTrue(all(n["meta"]["sid"] in by_sid for n in backed), "每个 sid 都有固化证据")
        for n in g.nodes.values():
            if n["kind"] == "SqlStmt":
                self.assertRegex(n["id"], r"^sql:[^:]+:[^:]+\.[^:]+$", n["id"])
            elif n["kind"] == "Route":
                self.assertRegex(n["id"], r"^route:[^:]+:(GET|POST|PUT|DELETE|PATCH|ANY) /", n["id"])
            elif n["kind"] == "Page":
                self.assertRegex(n["id"], r"^page:[^:]+:/", n["id"])

    def test_legacy_graph_without_sid_resolves_by_unique_rel(self):
        g, _ = graph_build(MINI, os.path.join(self.ws, "mini"))
        store = EvidenceStore(os.path.join(self.ws, "mini", "store.db"))
        self.addCleanup(store.close)
        resolver = EvidenceResolver(store)
        doc = next(n for n in g.nodes.values() if n["kind"] == "Doc")
        legacy = dict(doc, meta={k: v for k, v in doc["meta"].items() if k != "sid"})
        self.assertEqual(resolver.for_node(legacy), resolver.for_node(doc), "旧图（无 sid）按唯一 rel 回退")
        self.assertIsNone(resolver.for_node({"file": "nope/none.md", "meta": {}}))

    def test_rebind_moves_root_but_keeps_identity(self):
        repo = os.path.join(self.tmp, "loc-a", "mini")
        shutil.copytree(MINI, repo)
        out = os.path.join(self.ws, "mini")
        g1, _ = graph_build(repo, out)
        label = [d for d in os.listdir(out) if os.path.exists(os.path.join(out, d, "manifest.json"))][0]
        moved = os.path.join(self.tmp, "loc-b", "mini")
        os.makedirs(os.path.dirname(moved))
        shutil.move(repo, moved)
        info = batch.rebind(out, label, moved)
        self.assertEqual(info["root"], os.path.abspath(moved))
        with open(os.path.join(out, label, "manifest.json"), encoding="utf-8") as f:
            m = json.load(f)
        self.assertEqual(m["root"], os.path.abspath(moved))
        self.assertEqual(m["label"], label)
        g0, _, res0 = batch.update(out)
        self.assertIsNone(g0, "仅移动路径、内容未变：重绑后 update 应 no-op，不得整仓重建")
        with open(os.path.join(moved, "docs", "上线checklist.md"), "a", encoding="utf-8") as f:
            f.write("\n- 重绑后新增检查项\n")
        g2, _, res = batch.update(out)
        self.assertIsNotNone(g2)
        self.assertEqual([st for _, st in res], ["rebuild"])
        keep = lambda g: {i for i in g.nodes if not i.startswith("doc:")}
        self.assertEqual(keep(g1), keep(g2), "重绑不改变逻辑身份（非文档节点 ID 集合不变）")
        sids1 = {n["meta"].get("sid") for n in g1.nodes.values() if n["meta"].get("sid")}
        sids2 = {n["meta"].get("sid") for n in g2.nodes.values() if n["meta"].get("sid")}
        self.assertEqual(sids1, sids2, "sid 不随物理路径变化")
        with self.assertRaises(KeyError):
            batch.rebind(out, "not-registered", moved)
        with self.assertRaises(FileNotFoundError):
            batch.rebind(out, label, os.path.join(self.tmp, "missing"))


if __name__ == "__main__":
    unittest.main()
