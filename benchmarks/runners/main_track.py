#!/usr/bin/env python3
"""主轨运行器骨架：共同宿主/模型 + 每题新会话 + 预算硬顶 + 逐题账本。

真实宿主（Claude Code / Codex / ZCode / DSH + 真实模型版本）就绪后，只需实现
HostAdapter 并注册——编排、预算、账本、记录契约已由测试锁定。DryRunHost 为
确定性伪宿主（synthetic:true，永不作为正式证据）。
"""
import json
import os
import time
import uuid

GOLD_KEYS = {"gold", "gold_path", "answer", "expected", "evidence", "family",
             "cluster", "fact_ids", "necessary_facts"}
STATUS_OK = "ok"
STATUS_BUDGET_TOOL = "budget_exceeded_tool_calls"
STATUS_BUDGET_TOKENS = "budget_exceeded_tokens"
STATUS_BUDGET_CLOCK = "budget_exceeded_wall_clock"


class TrackBudget:
    def __init__(self, wall_clock_s=180, max_tool_calls=24, max_new_tokens=24000,
                 max_input=120000, max_output=8000):
        self.wall_clock_s = wall_clock_s
        self.max_tool_calls = max_tool_calls
        self.max_new_tokens = max_new_tokens
        self.max_input = max_input
        self.max_output = max_output


class DryRunHost:
    """确定性伪宿主：synthetic——管道契约测试用，产物不作正式证据。"""

    name = "dryrun"
    model = "synthetic:none"

    def __init__(self, turns=2, tokens_per_turn=(500, 200), tools_per_turn=3):
        self.turns = turns
        self.tokens_per_turn = tokens_per_turn
        self.tools_per_turn = tools_per_turn
        self.sessions = []

    def open_session(self, registration):
        sid = "sess-%s" % uuid.uuid4().hex[:12]
        self.sessions.append(sid)
        return {"id": sid, "registration": registration}

    def ask(self, session, question_text):
        return {"answer_text": "[dryrun] %s" % question_text[:40],
                "tool_calls": self.tools_per_turn,
                "tokens_in": self.tokens_per_turn[0],
                "tokens_out": self.tokens_per_turn[1],
                "secs": 0.01}

    def close_session(self, session):
        return None


class MainTrackRunner:
    def __init__(self, artifact_dir):
        self.artifact_dir = artifact_dir
        os.makedirs(artifact_dir, exist_ok=True)

    def run(self, system, host, questions, budget, registration=None):
        for question in questions:
            leaked = GOLD_KEYS & set(question)
            if leaked:
                raise ValueError("question %r leaks gold fields: %s"
                                 % (question.get("id"), sorted(leaked)))
        registration = registration or {"system": system, "enabled_products": [system]}
        records = []
        for question in questions:
            run_id = "mt-%s" % uuid.uuid4().hex[:16]
            started = time.time()
            session = host.open_session(registration)
            ledger = {"tool_calls": 0, "tokens_in": 0, "tokens_out": 0, "secs": 0.0}
            transcript = []
            status = STATUS_OK
            for _turn in range(getattr(host, "turns", 1)):
                if time.time() - started > budget.wall_clock_s:
                    status = STATUS_BUDGET_CLOCK
                    break
                turn = host.ask(session, question["query"])
                ledger["tool_calls"] += turn["tool_calls"]
                ledger["tokens_in"] += turn["tokens_in"]
                ledger["tokens_out"] += turn["tokens_out"]
                ledger["secs"] += turn["secs"]
                transcript.append(turn["answer_text"])
                if ledger["tool_calls"] > budget.max_tool_calls:
                    status = STATUS_BUDGET_TOOL
                    break
                if (ledger["tokens_in"] > budget.max_input
                        or ledger["tokens_out"] > budget.max_output
                        or ledger["tokens_in"] + ledger["tokens_out"] > budget.max_new_tokens):
                    status = STATUS_BUDGET_TOKENS
                    break
            host.close_session(session)
            tpath = os.path.join(self.artifact_dir, "%s.json" % run_id)
            with open(tpath, "w", encoding="utf-8") as stream:
                json.dump({"run_id": run_id, "question_id": question["id"],
                           "status": status, "ledger": ledger,
                           "transcript": transcript}, stream, ensure_ascii=False, indent=1)
            records.append({
                "schema": "domimap.maintrack.v1",
                "synthetic": host.model.startswith("synthetic"),
                "run_id": run_id, "question_id": question["id"], "system": system,
                "host": host.name, "model": host.model,
                "session_id": session["id"],
                "started": started, "ended": time.time(),
                "status": status, "ledger": ledger,
                "transcript_path": tpath})
        return records
