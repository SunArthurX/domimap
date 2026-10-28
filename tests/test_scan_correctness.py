"""扫描正确性：方法体归属、路由前缀、RPC implements、可插拔规则、Maven、DDL 注释。"""
import os
import shutil
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from domimap import lite_scan  # noqa: E402
from domimap.graph import Graph, load_seeds  # noqa: E402

SEEDS = os.path.join(ROOT, "domimap", "seeds.json")


def _write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(text).lstrip("\n"))


def _graph(root, rules=None):
    R = lite_scan.scan_repo(root, repo_label="ws", rules=rules)
    g = Graph()
    g.build_from_records(R, load_seeds(SEEDS))
    return g, R


class TestCallAttribution(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dm-calls-")
        self.addCleanup(shutil.rmtree, self.tmp)
        _write(self.tmp, "svc-a/src/main/java/a/A.java", """
            package a;
            public class A {
                private B b;
                public void one() {
                    log();
                }
                public void two() {
                    b.work();
                }
                public void three() {
                    x();
                }
                public void log() {}
                public void x() {}
            }
        """)
        _write(self.tmp, "svc-a/src/main/java/a/B.java", """
            package a;
            public class B {
                public void work() {}
            }
        """)
        _write(self.tmp, "svc-b/src/main/java/b/OtherA.java", """
            package b;
            public class A {
                public void noise() { log(); }
                public void log() {}
            }
        """)

    def _calls(self, g):
        out = []
        for e in g.edges:
            if e["kind"] != "CALLS":
                continue
            out.append((e["src"].split(":")[-1], e["dst"].split(":")[-1]))
        return sorted(out)

    def test_body_does_not_own_later_methods(self):
        g, _ = _graph(self.tmp)
        calls = [c for c in self._calls(g) if c[0] in {"A.one()", "A.two()", "A.three()"}]
        self.assertEqual(calls, [
            ("A.one()", "A.log()"),
            ("A.three()", "A.x()"),
            ("A.two()", "B.work()"),
        ], calls)

    def test_same_simple_name_other_file_does_not_share_bare_calls(self):
        g, _ = _graph(self.tmp)
        noise = [e for e in g.edges if e["kind"] == "CALLS" and "svc-b" in e["src"]]
        self.assertTrue(noise, "svc-b 的 noise() 应有一条同类调用")
        for e in noise:
            self.assertIn("svc-b", e["dst"], e)
            self.assertNotIn("svc-a", e["dst"], e)


class TestSpringRoutePrefix(unittest.TestCase):
    def test_class_prefix_keeps_extra_attributes(self):
        tmp = tempfile.mkdtemp(prefix="dm-route-")
        self.addCleanup(shutil.rmtree, tmp)
        _write(tmp, "svc/src/main/java/o/OrderController.java", """
            package o;
            @RestController
            @RequestMapping(value = "/order", produces = "application/json")
            public class OrderController {
                @PostMapping("/create")
                public void create() {}
            }
        """)
        g, _ = _graph(tmp)
        names = [n["name"] for n in g.nodes.values() if n["kind"] == "Route"]
        self.assertEqual(names, ["POST /order/create"], names)


class TestRpcImplements(unittest.TestCase):
    def test_provider_matches_implemented_interface(self):
        tmp = tempfile.mkdtemp(prefix="dm-rpc-")
        self.addCleanup(shutil.rmtree, tmp)
        _write(tmp, "order/pom.xml", """
            <project>
              <groupId>com.example</groupId>
              <artifactId>order</artifactId>
              <dependencies>
                <dependency><groupId>com.example</groupId><artifactId>pay</artifactId></dependency>
              </dependencies>
            </project>
        """)
        _write(tmp, "order/src/main/java/o/OrderServiceImpl.java", """
            package o;
            @DubboService
            public class OrderServiceImpl implements OrderService {
                public void create() {}
            }
        """)
        _write(tmp, "pay/src/main/java/p/PayService.java", """
            package p;
            public class PayService {
                @DubboReference
                private OrderService orderService;
                public void pay() { orderService.create(); }
            }
        """)
        g, _ = _graph(tmp)
        rpc = [(e["src"], e["dst"]) for e in g.edges if e["kind"] == "RPC"]
        self.assertTrue(any(s.endswith("p") or s.endswith(":p") or "PayService" in s or s.startswith("svc:")
                            for s, _ in rpc), rpc)
        self.assertTrue(any("order" in dst for _, dst in rpc), rpc)


class TestPluggableRules(unittest.TestCase):
    def test_workspace_rules_wire_custom_annotations(self):
        tmp = tempfile.mkdtemp(prefix="dm-rules-")
        self.addCleanup(shutil.rmtree, tmp)
        _write(tmp, "prov/src/main/java/p/Prov.java", """
            package p;
            @AcmeService
            public class Prov implements CatalogApi {
                public void ping() {}
            }
        """)
        _write(tmp, "cons/src/main/java/c/Cons.java", """
            package c;
            public class Cons {
                @AcmeReference
                private CatalogApi catalogApi;
            }
        """)
        rules = {"provider_annotations": ["AcmeService"], "consumer_annotations": ["AcmeReference"]}
        g, _ = _graph(tmp, rules=rules)
        rpc = [e for e in g.edges if e["kind"] == "RPC"]
        self.assertTrue(rpc, "自定义注解规则应产出 RPC 边")
        self.assertTrue(any("cons" in e["src"] and "prov" in e["dst"] for e in rpc), rpc)


class TestMavenAndDdl(unittest.TestCase):
    def test_pom_dependency_edge(self):
        tmp = tempfile.mkdtemp(prefix="dm-pom-")
        self.addCleanup(shutil.rmtree, tmp)
        _write(tmp, "order/pom.xml", """
            <project xmlns="http://maven.apache.org/POM/4.0.0">
              <groupId>com.example</groupId>
              <artifactId>order</artifactId>
              <dependencies>
                <dependency><groupId>com.example</groupId><artifactId>pay</artifactId></dependency>
              </dependencies>
            </project>
        """)
        _write(tmp, "pay/pom.xml", """
            <project>
              <groupId>com.example</groupId>
              <artifactId>pay</artifactId>
            </project>
        """)
        g, _ = _graph(tmp)
        deps = [e for e in g.edges if e["kind"] == "DEPENDS_ON"]
        self.assertEqual(len(deps), 1, deps)
        self.assertIn("order", deps[0]["src"])
        self.assertIn("pay", deps[0]["dst"])

    def test_ddl_comment_is_searchable(self):
        tmp = tempfile.mkdtemp(prefix="dm-ddl-")
        self.addCleanup(shutil.rmtree, tmp)
        _write(tmp, "db/schema.sql", """
            CREATE TABLE t_price_adj (
              id BIGINT PRIMARY KEY,
              adj_amt DECIMAL(10,2) COMMENT '改价金额'
            ) COMMENT='订单改价单';
        """)
        g, _ = _graph(tmp)
        from domimap.search import Searcher
        r = Searcher(g).query("改价金额", seeds=load_seeds(SEEDS))
        names = [n["name"] for n in r["seeds"]]
        self.assertTrue(any(n in {"t_price_adj", "adj_amt"} for n in names), (names, r["text"][:400]))

    def test_mybatis_plus_annotation_sql_and_feign_app_name(self):
        tmp = tempfile.mkdtemp(prefix="dm-mp-")
        self.addCleanup(shutil.rmtree, tmp)
        _write(tmp, "order/src/main/resources/application.yml", """
            spring:
              application:
                name: order-app
        """)
        _write(tmp, "order/src/main/java/o/PriceAdj.java", """
            package o;
            @TableName("t_price_adj")
            public class PriceAdj {}
        """)
        _write(tmp, "order/src/main/java/o/PriceMapper.java", """
            package o;
            public interface PriceMapper {
                @Select("SELECT id FROM t_price_adj WHERE id = 1")
                PriceAdj find(Long id);
            }
        """)
        _write(tmp, "pay/src/main/java/p/OrderClient.java", """
            package p;
            @FeignClient(name = "order-app")
            public interface OrderClient {}
        """)
        g, _ = _graph(tmp)
        self.assertTrue(any(n["kind"] == "Table" and n["name"] == "t_price_adj" for n in g.nodes.values()))
        self.assertTrue(any(e["kind"] == "MAPS_TO" for e in g.edges), "TableName 应连到表")
        self.assertTrue(any(e["kind"] == "READS" for e in g.edges), "@Select 应读表")
        rpc = [e for e in g.edges if e["kind"] == "RPC"]
        self.assertTrue(any("pay" in e["src"] and "order" in e["dst"] for e in rpc), rpc)

    def test_enum_and_second_class_are_nodes(self):
        tmp = tempfile.mkdtemp(prefix="dm-enum-")
        self.addCleanup(shutil.rmtree, tmp)
        _write(tmp, "svc/src/main/java/s/Types.java", """
            package s;
            public enum PriceMode { MANUAL, AUTO }
            public class Helper {
                @Scheduled(cron = "0 0 * * * *")
                public void nightly() {}
            }
        """)
        g, _ = _graph(tmp)
        kinds = {(n["kind"], n["name"]) for n in g.nodes.values()}
        self.assertIn(("Class", "PriceMode"), kinds)
        self.assertIn(("Class", "Helper"), kinds)
        self.assertTrue(any(n["kind"] == "Job" and n["name"] == "nightly" for n in g.nodes.values()),
                        [n["name"] for n in g.nodes.values() if n["kind"] == "Job"])


if __name__ == "__main__":
    unittest.main()
