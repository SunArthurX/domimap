"""RV03 回归（AC-R05-01 / AC-R06-02 / AC-F4-02）：审定绑定版本与陈述身份；审计事件；提案/审定权限分离。

复现自 out/agent-review-2026-10-27/reproductions.json：用户看过 revision 1 的陈述 A，
另一写者改为 revision 2 的 B 后，旧 accept(note_id, idx) 仍成功批准 B。
"""
import json
import os
import tempfile
import unittest

from domimap import mcp
from domimap.graph import build as graph_build
from domimap.knowledge import KnowledgeStore, ConflictError
from domimap.service import AppService, ServiceError

CLAIMS_A = [{"type": "decision", "statement": "改价必须走审批", "evidence": [], "scope": "order"}]
CLAIMS_B = [{"type": "decision", "statement": "改价禁止审批（新版）", "evidence": [], "scope": "order"}]


class TestAdjudicationContract(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dm-rv03-")
        self.addCleanup(tmp.cleanup)
        self.ws = os.path.join(tmp.name, "ws")
        graph_build("tests/fixtures/mini", self.ws)
        self.gp = os.path.join(self.ws, "graph.json")
        self.kb_path = os.path.join(self.ws, "knowledge.db")
        os.environ.pop("DOMIMAP_MCP_ADJUDICATE", None)

    def _note(self):
        kb = KnowledgeStore(self.kb_path)
        try:
            return kb.submit("改价结论", claims=CLAIMS_A, idempotency_key="k-rv03")
        finally:
            kb.close()

    def test_accept_binds_revision_and_statement_identity(self):
        r = self._note()
        kb = KnowledgeStore(self.kb_path)
        try:
            # 另一写者改为 B（revision 2）
            kb.amend(r["note_id"], "改价结论 v2", expected_revision=1, claims=CLAIMS_B)
            # 旧审定请求（基于 revision 1 / 陈述 A）必须冲突，不得批准 B
            with self.assertRaises(ConflictError):
                kb.accept_claim(r["note_id"], 0, expected_revision=1,
                                statement="改价必须走审批")
            # 陈述身份不符（同 revision 但内容被换）也必须冲突
            with self.assertRaises(ConflictError):
                kb.accept_claim(r["note_id"], 0, expected_revision=2,
                                statement="完全不同的陈述")
            # 正确绑定 → 成功且状态 accepted
            out = kb.accept_claim(r["note_id"], 0, expected_revision=2,
                                  statement="改价禁止审批（新版）",
                                  auditor="human:test", reason="复核新依据")
            self.assertEqual(out["state"], "accepted")
        finally:
            kb.close()

    def test_accept_without_binding_is_refused(self):
        r = self._note()
        kb = KnowledgeStore(self.kb_path)
        try:
            with self.assertRaises(TypeError):
                kb.accept_claim(r["note_id"], 0)  # 不带绑定参数的旧式调用不再被接受
        finally:
            kb.close()

    def test_review_events_are_appended_and_reconstructable(self):
        r = self._note()
        kb = KnowledgeStore(self.kb_path)
        try:
            kb.accept_claim(r["note_id"], 0, expected_revision=1,
                            statement="改价必须走审批", auditor="human:alice", reason="看过依据")
            kb.withdraw(r["note_id"], auditor="human:alice", reason="过期")
            events = kb.review_events(r["note_id"])
            actions = [e["action"] for e in events]
            self.assertIn("accept", actions)
            self.assertIn("withdraw", actions)
            acc = next(e for e in events if e["action"] == "accept")
            self.assertEqual(acc["auditor"], "human:alice")
            self.assertEqual(acc["reason"], "看过依据")
            self.assertEqual(acc["expected_revision"], 1)
            self.assertIn("改价必须走审批", acc["statement"])
            wd = next(e for e in events if e["action"] == "withdraw")
            self.assertEqual(wd["auditor"], "human:alice")
        finally:
            kb.close()

    def test_service_accept_requires_binding_and_mcp_needs_separate_authorization(self):
        r = self._note()
        svc = AppService(self.gp)
        with self.assertRaises(ServiceError) as cm:
            svc.note_accept(r["note_id"], 0)  # 缺绑定 → invalid_params
        self.assertEqual(cm.exception.code, "invalid_params")
        out = svc.note_accept(r["note_id"], 0, expected_revision=1,
                              statement="改价必须走审批", auditor="human:cli")
        self.assertEqual(out["state"], "accepted")

        # MCP：--enable-write 只授权写入（提案/修订），不等于人工审定
        kb = KnowledgeStore(self.kb_path)
        try:
            kb.amend(r["note_id"], "v3", expected_revision=1, claims=CLAIMS_A)  # 回到 proposed
        finally:
            kb.close()
        srv = mcp.Server(self.gp, enable_write=True)
        res = srv.call("kg_note", {"action": "accept", "note_id": r["note_id"],
                                   "claim_idx": 0, "expected_revision": 2,
                                   "statement": "改价必须走审批"})
        self.assertTrue(res["isError"], "MCP 审定未单独授权必须失败")
        body = json.loads(res["content"][0]["text"])
        self.assertEqual(body["code"], "forbidden")
        self.assertIn("DOMIMAP_MCP_ADJUDICATE", body["message"])
        # 单独授权后可用，且审计记录来源为 agent
        os.environ["DOMIMAP_MCP_ADJUDICATE"] = "1"
        try:
            res = srv.call("kg_note", {"action": "accept", "note_id": r["note_id"],
                                       "claim_idx": 0, "expected_revision": 2,
                                       "statement": "改价必须走审批"})
            self.assertFalse(res["isError"], res)
            kb = KnowledgeStore(self.kb_path)
            try:
                ev = kb.review_events(r["note_id"])
                acc = [e for e in ev if e["action"] == "accept"][-1]  # 取最后一次审定（本例为 agent）
                self.assertTrue(acc["auditor"].startswith("agent:"), acc["auditor"])
            finally:
                kb.close()
        finally:
            os.environ.pop("DOMIMAP_MCP_ADJUDICATE", None)

    def test_withdrawn_note_cannot_be_accepted(self):
        r = self._note()
        kb = KnowledgeStore(self.kb_path)
        try:
            kb.withdraw(r["note_id"], auditor="human:x")
            with self.assertRaises(ConflictError):
                kb.accept_claim(r["note_id"], 0, expected_revision=1,
                                statement="改价必须走审批")
        finally:
            kb.close()


if __name__ == "__main__":
    unittest.main()
