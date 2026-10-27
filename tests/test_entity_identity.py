"""RV02 回归（AC-R01-01 / AC-R09-02）：重载身份与跨仓同名实体；构建顺序无关性。

复现自 out/agent-review-2026-10-27/reproductions.json：
- 同仓 `find(String)` / `find(Integer)` 因参数数量相同被合并 → 应按完整签名分开；
- 两仓各自 DDL 的 `t_order` 合并为一个节点且出处随构建顺序变化 → 应按声明方隔离、引用显式连接、顺序无关。
"""
import os
import tempfile
import unittest

from domimap.graph import Graph, load_seeds
from domimap import lite_scan

HERE = os.path.dirname(os.path.abspath(__file__))
SEEDS = load_seeds(os.path.join(os.path.dirname(HERE), "domimap", "seeds.json"))

JAVA = """package com.%(pkg)s.order;
public class Finder {
    public String find(String key) { return key; }
    public Integer find(Integer id) { return id; }
}
"""
DDL = "-- t_order DDL (%(pkg)s)\nCREATE TABLE t_order (id BIGINT, price DECIMAL, note VARCHAR(64));\n"
MAPPER = """<?xml version="1.0"?>
<mapper namespace="com.%(pkg)s.order.OrderMapper">
  <update id="updatePrice">UPDATE t_order SET price=#{p} WHERE id=#{id}</update>
</mapper>
"""


def _repo(base, pkg, with_ddl=True, with_mapper=False):
    root = os.path.join(base, pkg)  # 仓目录名 = pkg（两仓 basename 不同，标签不冲突）
    os.makedirs(os.path.join(root, "order-service", "src", "com", pkg, "order"))
    os.makedirs(os.path.join(root, "order-service", "sqlmap"))
    open(os.path.join(root, "pom.xml"), "w").write("<project/>")
    open(os.path.join(root, "order-service", "src", "com", pkg, "order", "Finder.java"), "w").write(JAVA % {"pkg": pkg})
    if with_ddl:
        open(os.path.join(root, "order-service", "sqlmap", "schema.sql"), "w").write(DDL % {"pkg": pkg})
    if with_mapper:
        open(os.path.join(root, "order-service", "sqlmap", "OrderMapper.xml"), "w").write(MAPPER % {"pkg": pkg})
    return root


def _scan_and_build(roots):
    merged = {"services": {}, "classes": [], "methods": [], "routes": [], "rpc": [], "topics": [],
              "sqlstmts": [], "tables": [], "pages": [], "docs": [], "entities": [], "calls": [],
              "coverage": {"files_scanned": 0, "skipped": []}}
    for root in roots:
        label = os.path.basename(root)
        R = lite_scan.scan_repo(root, repo_label=label)
        for k in ("classes", "methods", "routes", "rpc", "topics", "sqlstmts", "tables", "pages", "docs", "entities", "calls"):
            merged[k].extend(R[k])
        merged["services"].update(R["services"])
    g = Graph()
    g.build_from_records(merged, SEEDS)
    return g


class TestOverloadIdentity(unittest.TestCase):
    def test_same_argc_overloads_stay_separate(self):
        with tempfile.TemporaryDirectory(prefix="dm-rv02-") as tmp:
            repo = _repo(tmp, "alpha", with_ddl=False)
            g = _scan_and_build([repo])
            finders = sorted(n["id"] for n in g.nodes.values()
                             if n["kind"] == "Method" and n["name"] == "find")
            self.assertEqual(len(finders), 2, "find(String) 与 find(Integer) 必须是两个方法节点：%s" % finders)
            self.assertIn("String", finders[0] + finders[1])
            self.assertIn("Integer", finders[0] + finders[1])

    def test_cross_repo_same_name_methods_stay_separate(self):
        with tempfile.TemporaryDirectory(prefix="dm-rv02-") as tmp:
            a, b = _repo(tmp, "alpha", with_ddl=False), _repo(tmp, "beta", with_ddl=False)
            g = _scan_and_build([a, b])
            finders = [n["id"] for n in g.nodes.values() if n["kind"] == "Method" and n["name"] == "find"]
            self.assertEqual(len(finders), 4, "两仓各两个重载 → 4 个节点：%s" % finders)


class TestTableIdentity(unittest.TestCase):
    def test_same_name_ddl_tables_isolated_and_order_independent(self):
        with tempfile.TemporaryDirectory(prefix="dm-rv02-") as tmp:
            a, b = _repo(tmp, "alpha"), _repo(tmp, "beta")
            g1 = _scan_and_build([a, b])
            g2 = _scan_and_build([b, a])
            t1 = {n["id"]: n for n in g1.nodes.values() if n["kind"] == "Table"}
            t2 = {n["id"]: n for n in g2.nodes.values() if n["kind"] == "Table"}
            self.assertEqual(len(t1), 2, "两仓同名 DDL 表必须隔离为两个节点：%s" % sorted(t1))
            self.assertEqual(set(t1), set(t2), "表 ID 集合与构建顺序无关")
            for nid in t1:
                self.assertEqual(t1[nid]["meta"].get("sid"), t2[nid]["meta"].get("sid"),
                                 "节点出处（sid）与构建顺序无关：%s" % nid)
            self.assertEqual(sorted(str(sorted(e.items())) for e in g1.edges),
                             sorted(str(sorted(e.items())) for e in g2.edges),
                             "边集合与构建顺序无关")

    def test_mapper_reference_single_candidate_joins_explicitly(self):
        with tempfile.TemporaryDirectory(prefix="dm-rv02-") as tmp:
            a = _repo(tmp, "alpha", with_ddl=True, with_mapper=True)
            g = _scan_and_build([a])
            tables = [n for n in g.nodes.values() if n["kind"] == "Table"]
            self.assertEqual(len(tables), 1, "同仓 DDL+Mapper：单候选显式连接，仍一个表节点")
            writes = [e for e in g.edges if e["kind"] == "WRITES"]
            self.assertEqual(len(writes), 1)
            self.assertEqual(writes[0]["dst"], tables[0]["id"])

    def test_cross_repo_mapper_multi_candidate_is_ambiguous_not_merged(self):
        with tempfile.TemporaryDirectory(prefix="dm-rv02-") as tmp:
            a = _repo(tmp, "alpha", with_ddl=True, with_mapper=True)
            b = _repo(tmp, "beta", with_ddl=True, with_mapper=False)
            g = _scan_and_build([a, b])
            tables = [n for n in g.nodes.values() if n["kind"] == "Table"]
            self.assertEqual(len(tables), 2, "两仓 DDL 表隔离")
            writes = [e for e in g.edges if e["kind"] == "WRITES"]
            self.assertEqual(len(writes), 2, "alpha 的 mapper 引用 t_order 有两个同名候选 → 各连一条 AMBIGUOUS 边，不合并")
            self.assertTrue(all(e["conf"] == "AMBIGUOUS" for e in writes),
                            "多候选引用必须显式不确定：%s" % writes)
            dsts = sorted(e["dst"] for e in writes)
            self.assertEqual(dsts, sorted(t["id"] for t in tables))

    def test_legacy_short_mth_ids_not_created(self):
        with tempfile.TemporaryDirectory(prefix="dm-rv02-") as tmp:
            repo = _repo(tmp, "alpha", with_ddl=False)
            g = _scan_and_build([repo])
            for n in g.nodes.values():
                if n["kind"] == "Method":
                    self.assertIn("(", n["id"], "方法 ID 必须携带完整参数签名：%s" % n["id"])


TOPIC_SEND = """package com.%(pkg)s.pub;
import org.apache.rocketmq.spring.core.RocketMQTemplate;
public class Pub {
    private RocketMQTemplate rocketMQTemplate;
    public void emit() { rocketMQTemplate.syncSend("%(topic)s", "m"); }
}
"""
KAFKA_LISTEN = """package com.%(pkg)s.sub;
import org.springframework.kafka.annotation.KafkaListener;
public class K {
    @KafkaListener(topics = "%(topic)s")
    public void on(String m) { }
}
"""
RMQ_LISTEN = """package com.%(pkg)s.sub;
import org.apache.rocketmq.spring.annotation.RocketMQMessageListener;
@RocketMQMessageListener(topic = "%(topic)s", consumerGroup = "g")
public class L {
    public void onMessage(String m) { }
}
"""


def _topic_repo(base, pkg, topic, files):
    root = os.path.join(base, pkg)
    os.makedirs(os.path.join(root, "src"), exist_ok=True)
    open(os.path.join(root, "pom.xml"), "w").write("<project/>")
    for name, text in files.items():
        open(os.path.join(root, "src", name), "w").write(text)
    return root


class TestTopicClusterIdentity(unittest.TestCase):
    def test_same_cluster_pubsub_joins_with_explicit_basis(self):
        with tempfile.TemporaryDirectory(prefix="dm-rv02b-") as tmp:
            a = _topic_repo(tmp, "alpha", "trade-events",
                            {"Pub.java": TOPIC_SEND % {"pkg": "alpha", "topic": "trade-events"}})
            b = _topic_repo(tmp, "beta", "trade-events",
                            {"L.java": RMQ_LISTEN % {"pkg": "beta", "topic": "trade-events"}})
            for repos in ([a, b], [b, a]):
                g = _scan_and_build(repos)
                nodes = [n for n in g.nodes.values() if n["kind"] == "Topic"]
                self.assertEqual(len(nodes), 1, "同集群（rocketmq）同名主题应连接为一个节点")
                n = nodes[0]
                self.assertTrue(n["id"].startswith("topic:rocketmq:"), n["id"])
                self.assertEqual(sorted(n["meta"]["services"]), ["alpha", "beta"],
                                 "参与方列表确定且与构建顺序无关")
                self.assertTrue(n["meta"].get("shared_basis"), "共享必须有明确依据说明")
                pub = [e for e in g.edges if e["kind"] == "PUBLISHES"]
                sub = [e for e in g.edges if e["kind"] == "SUBSCRIBES"]
                self.assertEqual(len(pub), 1); self.assertEqual(len(sub), 1)

    def test_same_name_different_cluster_stays_isolated(self):
        with tempfile.TemporaryDirectory(prefix="dm-rv02b-") as tmp:
            a = _topic_repo(tmp, "alpha", "trade-events",
                            {"Pub.java": TOPIC_SEND % {"pkg": "alpha", "topic": "trade-events"}})
            b = _topic_repo(tmp, "beta", "trade-events",
                            {"K.java": KAFKA_LISTEN % {"pkg": "beta", "topic": "trade-events"}})
            g = _scan_and_build([a, b])
            topics = sorted(n["id"] for n in g.nodes.values() if n["kind"] == "Topic")
            self.assertEqual(topics, ["topic:kafka:trade-events", "topic:rocketmq:trade-events"],
                             "跨数据源（消息集群）同名主题必须保持独立节点")
            between = [e for e in g.edges if e["src"] in topics and e["dst"] in topics]
            self.assertEqual(between, [], "不同集群之间不得有任何共享边")

    def test_topic_identity_order_independent(self):
        with tempfile.TemporaryDirectory(prefix="dm-rv02b-") as tmp:
            a = _topic_repo(tmp, "alpha", "t", {"Pub.java": TOPIC_SEND % {"pkg": "alpha", "topic": "t"}})
            b = _topic_repo(tmp, "beta", "t", {"L.java": RMQ_LISTEN % {"pkg": "beta", "topic": "t"}})
            g1, g2 = _scan_and_build([a, b]), _scan_and_build([b, a])
            key = lambda g: sorted((n["id"], n["meta"].get("services") and tuple(n["meta"]["services"]),
                                    tuple(sorted(str(sorted(e.items())) for e in g.edges)))
                                   for n in g.nodes.values() if n["kind"] == "Topic")
            self.assertEqual(key(g1), key(g2), "Topic 节点/出处/边与构建顺序全等")


if __name__ == "__main__":
    unittest.main()
