"""类注释关键词召回契约（product-comment-recall）。

第 5 步诊断驱动：企业 Dao 仓类 recall miss——中文注释词与 Class 节点词面零交集。
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from domimap import lite_scan  # noqa: E402

JAVA = """package com.example.pop.dao.delivery;

/**
 * 配送 区域 限额 任务 DAO
 * 负责区域限额规则的持久化
 */
public class AreaLimitTaskDao {
    public int insert(Object o) { return 0; }
}
"""

JAVA_NO_COMMENT = """package com.example.pop.dao.delivery;

public class PlainDao {
    public int insert(Object o) { return 0; }
}
"""


def build_graph(files):
    base = tempfile.mkdtemp(prefix="dm-cmt-")
    for rel, content in files.items():
        path = os.path.join(base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write(content)
    R = lite_scan.scan_repo(base)
    from domimap.graph import Graph, load_seeds
    g = Graph()
    g.build_from_records(R, load_seeds(os.path.join(ROOT, "domimap", "seeds.json")))
    from domimap.search import Searcher
    return Searcher(g), R


class TestCommentRecall(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.searcher, cls.records = build_graph(
            {"src/main/java/com/example/pop/dao/delivery/AreaLimitTaskDao.java": JAVA,
             "src/main/java/com/example/pop/dao/delivery/PlainDao.java": JAVA_NO_COMMENT})

    def test_comment_captured_in_records(self):
        # 按名字查找而非下标：目录遍历顺序随平台/文件系统不同（Linux CI 上 PlainDao 曾排前）
        by_name = {r["name"]: r for r in self.records["classes"]}
        cls_rec = by_name["AreaLimitTaskDao"]
        for word in ("配送", "区域", "限额"):
            self.assertIn(word, cls_rec["comment"])
        self.assertEqual(by_name["PlainDao"]["comment"], "")

    def test_comment_keywords_retrieve_class(self):
        result = self.searcher.query("配送 区域 限额 处理", top_k=5)
        files = [n.get("file") for n in result.get("seeds", [])]
        self.assertTrue(any("AreaLimitTaskDao.java" in (f or "") for f in files),
                        "注释关键词应命中 Dao 类: %s" % files)

    def test_comment_does_not_leak_to_unrelated(self):
        result = self.searcher.query("配送 区域 限额 处理", top_k=5)
        files = [n.get("file") for n in result.get("seeds", [])]
        self.assertFalse(any("PlainDao.java" in (f or "") for f in files))

    def test_identifier_search_unchanged(self):
        result = self.searcher.query("AreaLimitTaskDao", top_k=5)
        files = [n.get("file") for n in result.get("seeds", [])]
        self.assertTrue(any("AreaLimitTaskDao.java" in (f or "") for f in files))

    def test_absent_identifier_still_refused(self):
        result = self.searcher.query("NoSuchDaoAnywhere", top_k=5)
        self.assertTrue(result.get("refused"))


if __name__ == "__main__":
    unittest.main()
