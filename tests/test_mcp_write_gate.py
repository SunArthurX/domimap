"""MCP 写能力显式启用（roadmap M3：写能力明确启用、与只读分开；转达判定不作人源）。

AC-R08-02/AC-R15-02 方向：默认 serve 只公布 6 个只读工具；kg_feedback 须 --enable-write；
经 MCP 提交的判定以 agent_relay 来源落库，不进 AUTHORITATIVE_SOURCES，不改变命中率口径。
"""
import os
import tempfile
import unittest
from pathlib import Path

from domimap import mcp
from domimap.feedback import FeedbackStore, AUTHORITATIVE_SOURCES, SOURCE_VALUES
from domimap.graph import Graph
from domimap.observation import run_query


class TestMcpWriteGate(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dm-mcp-write-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        g = Graph()
        g.add_node("doc:fixture", "Doc", "fixture", "input.md", {"text": "version"})
        g.save(str(self.root / "graph.json"))
        self.graph = str(self.root / "graph.json")
        self._observe = os.environ.pop("DOMIMAP_OBSERVE", None)
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        if self._observe is not None:
            os.environ["DOMIMAP_OBSERVE"] = self._observe

    def _names(self, srv):
        r = mcp._response(srv, {"jsonrpc": "2.0", "id": 1,
                                "method": "tools/list", "params": {}})
        return {t["name"] for t in r["result"]["tools"]}

    def test_default_server_lists_only_six_read_tools(self):
        names = self._names(mcp.Server(self.graph))
        self.assertEqual(len(names), 7, names)  # 6 检索/读取 + kg_context（F3）
        self.assertNotIn("kg_feedback", names)

    def test_enable_write_lists_feedback_tool(self):
        names = self._names(mcp.Server(self.graph, enable_write=True))
        self.assertIn("kg_feedback", names)
        self.assertEqual(len(names), 8)

    def test_disabled_write_call_is_explicit_error(self):
        srv = mcp.Server(self.graph)
        r = srv.call("kg_feedback", {"event_id": "qe:" + "0" * 24, "relevance": "hit"})
        self.assertTrue(r["isError"])
        self.assertIn("write_disabled", r["content"][0]["text"])

    def test_enabled_write_records_non_authoritative_relay_source(self):
        srv = mcp.Server(self.graph, enable_write=True)
        _, obs = run_query(self.graph, srv.s, "fixture", "mcp",
                           {"top_k": 6, "seeds": srv.seeds})
        self.assertEqual(obs["status"], "recorded", obs)
        qid = obs["event_id"]
        r = srv.call("kg_feedback", {"event_id": qid, "relevance": "hit"})
        self.assertFalse(r["isError"], r)
        store = FeedbackStore(str(self.root / "queries.db"))
        self.addCleanup(store.db.close)
        rows = store.db.execute("SELECT source FROM feedback WHERE event_id=?", (qid,)).fetchall()
        self.assertEqual([row[0] for row in rows], ["agent_relay"])
        self.assertIn("agent_relay", SOURCE_VALUES)
        self.assertNotIn("agent_relay", AUTHORITATIVE_SOURCES)

    def test_visible_tools_helper_matches_server_contract(self):
        self.assertEqual({t["name"] for t in mcp.visible_tools(False)},
                         {"kg_explore", "kg_domain_map", "kg_impact",
                          "kg_doc_search", "kg_read", "kg_troubleshoot", "kg_context"})
        self.assertEqual(len(mcp.visible_tools(True)), len(mcp.TOOLS))


if __name__ == "__main__":
    unittest.main()
