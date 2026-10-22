"""查询构造纪律契约（product-query-discipline）。

诊断（out/semantic-bridge-ab/citation-diagnosis.json）：19 个 agent miss 中 15 个 gold
从未经工具输出，其中 4 个检索级（原文直查+embed）可命中——agent 改写查询丢失原文 bigram。
产品表面（kg_explore 工具描述）与评测宿主（TOOLS_SPEC/SYSTEM_PROMPT）加"原文直查优先 +
引用守门"指引；检索本体与题目/评分器/预算零改动（R14 反作弊红线）。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from domimap import mcp  # noqa: E402

QUERY_MARK = "直接使用问题原文"
CITE_MARK = "只引用检索结果中出现过的"


class TestQueryDiscipline(unittest.TestCase):
    def _kg_explore(self):
        return next(t for t in mcp.TOOLS if t["name"] == "kg_explore")

    def test_tool_description_carries_discipline(self):
        desc = self._kg_explore()["description"]
        self.assertIn(QUERY_MARK, desc, "查询指引必须在工具描述中")
        self.assertIn(CITE_MARK[:8], desc.replace("@ ", ""), "引用守门必须在工具描述中")

    def test_tool_schema_unchanged(self):
        tool = self._kg_explore()
        spec = tool["inputSchema"]
        self.assertEqual(sorted(spec["properties"]), ["domain", "query", "top_k"])
        self.assertEqual(tool.get("required", spec.get("required")), ["query"])

    def test_host_prompt_and_spec_in_sync(self):
        path = os.path.join(ROOT, "benchmarks", "runners", "glm_host.py")
        text = open(path, encoding="utf-8").read()
        self.assertIn(QUERY_MARK, text, "宿主 SYSTEM_PROMPT/TOOLS_SPEC 同步查询指引")
        self.assertIn("不要引用未在结果中出现的路径", text, "宿主引用守门在位")

    def test_other_tools_untouched(self):
        names = {t["name"] for t in mcp.TOOLS}
        self.assertEqual(names, {"kg_explore", "kg_domain_map", "kg_impact",
                                 "kg_doc_search", "kg_read", "kg_troubleshoot"})


if __name__ == "__main__":
    unittest.main()
