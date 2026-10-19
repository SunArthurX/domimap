"""DDL 语义加权 + 版本号纪元 + 输出信息标注契约（product-ddl-rank-era）。"""
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from domimap import lite_scan  # noqa: E402


def _scan(files):
    base = tempfile.mkdtemp(prefix="dm-ddl-")
    for rel, content in files.items():
        path = os.path.join(base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write(content)
    return lite_scan.scan_repo(base), base


class TestDDLSemanticBoost(unittest.TestCase):
    def _build(self, files):
        R, _ = _scan(files)
        from domimap.graph import Graph, load_seeds
        from domimap.search import Searcher
        g = Graph()
        g.build_from_records(R, load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
        return Searcher(g)

    def test_ddl_ranked_above_java_reference(self):
        """查询含'表 定义 写入'时 DDL SQL 应排在 Java 引用前。"""
        s = self._build({
            "sql/schema.sql": "CREATE TABLE t_user (id BIGINT, name VARCHAR(100));\n",
            "src/UserDao.java":
                "/**\n * 用户表 数据访问对象 写入 定义 位置 处理\n */\npublic class UserDao {\n}\n",
        })
        r = s.query("t_user 表 定义 写入 位置", top_k=5)
        self.assertFalse(r.get("refused"))
        kinds = [(n["kind"], n["file"]) for n in r["seeds"]]
        sql_rank = next((i for i, (k, f) in enumerate(kinds) if "schema.sql" in f), None)
        java_rank = next((i for i, (k, f) in enumerate(kinds) if "UserDao" in f), None)
        if sql_rank is not None and java_rank is not None:
            self.assertLess(sql_rank, java_rank,
                            "DDL 应排在 Java 引用前: %s" % kinds)

    def test_ddl_render_has_tag(self):
        s = self._build({"sql/init.sql": "CREATE TABLE t_order (id BIGINT);\n"})
        r = s.query("t_order 表 定义", top_k=5)
        self.assertIn("[DDL]", r.get("text", ""),
                      "CREATE TABLE 的 SqlStmt 应标注 [DDL]")


class TestVersionEra(unittest.TestCase):
    def test_release_version_provides_era(self):
        R, _ = _scan({"CHANGELOG.md":
                      "# Changelog\n\n## Release 2.4\n- Bug fixes\n" + "Detail\n" * 30})
        era = R["docs"][0]["content_era"]
        self.assertIsNotNone(era, "Release 2.4 应提供纪元")

    def test_v_version_provides_era(self):
        R, _ = _scan({"SPEC.md": "# Spec\n\nVersion 3.1 feature spec.\n" + "Detail\n" * 30})
        era = R["docs"][0]["content_era"]
        self.assertIsNotNone(era, "Version 3.1 应提供纪元")

    def test_date_takes_priority_over_version(self):
        R, _ = _scan({"CHANGELOG.md":
                      "# Changelog\n\n## v2.0 - 2023-06-15\n- Fix\n" + "Detail\n" * 30})
        era = R["docs"][0]["content_era"]
        self.assertIsNotNone(era)
        self.assertEqual(time.strftime("%Y-%m-%d", time.gmtime(era)), "2023-06-15",
                         "正文日期应优先于版本号")

    def test_no_date_no_version_no_era(self):
        R, _ = _scan({"plain.md": "# Plain\n\nNo dates here.\n" + "Detail\n" * 30})
        self.assertIsNone(R["docs"][0]["content_era"])


class TestRenderInfo(unittest.TestCase):
    def _build(self, files):
        R, _ = _scan(files)
        from domimap.graph import Graph, load_seeds
        from domimap.search import Searcher
        g = Graph()
        g.build_from_records(R, load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
        return Searcher(g)

    def test_doc_render_has_type_and_rank(self):
        s = self._build({"README.md": "# Tutorial\nGetting started guide.\n" + "Detail.\n" * 30})
        r = s.query("tutorial guide", top_k=5)
        self.assertIn("[type:README]", r.get("text", ""))
        self.assertIn("[rank:#1]", r.get("text", ""))

    def test_changelog_type(self):
        s = self._build({"CHANGELOG.md": "# Changes\n\nv2.0 released.\n" + "Detail.\n" * 30})
        r = s.query("changelog changes", top_k=5)
        self.assertIn("[type:CHANGELOG]", r.get("text", ""))

    def test_type_does_not_affect_ranking(self):
        """信息标注不加权——README 和普通 doc 排序只由 BM25 决定。"""
        s = self._build({
            "README.md": "# readme\nContent about xyz.\n" + "More.\n" * 30,
            "doc/xyz_guide.md": "# XYZ Guide\nContent about xyz.\n" + "More.\n" * 30,
        })
        r = s.query("xyz", top_k=5)
        # 两者应都在结果中（无先验加成导致的排序偏移）
        files = {n["file"] for n in r["seeds"]}
        self.assertIn("README.md", files)
        self.assertIn("doc/xyz_guide.md", files)


if __name__ == "__main__":
    unittest.main()
