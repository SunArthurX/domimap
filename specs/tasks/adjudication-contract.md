# adjudication-contract — RV03：审定绑定版本与陈述身份；审计事件；提案/审定权限分离

依据 out/agent-review-2026-10-27/review.md RV03（复现：看过 rev1 陈述 A，他人改为 rev2 的 B 后，旧 accept(note,idx) 仍批准 B）。

## 修复：`accept_claim(note_id, idx, expected_revision, statement, auditor, reason)`——事务内校验笔记 revision 与陈述原文一致，不符 ConflictError；无绑定参数的旧式调用 TypeError 拒绝；撤回后的笔记不可审定。新增 `review_events` 表（append-only 审计：action/statement/expected_revision/auditor/reason/at），accept 与 withdraw 均记事件，`review_events(note_id)` 可重建历史。权限分离：`service.note_accept_agent`（MCP 路径）须 `DOMIMAP_MCP_ADJUDICATE=1` 单独授权（`--enable-write` 只授权提案/修订），审计 auditor=`agent:mcp`；CLI 审定 auditor=`human:$USER`，须 `--expected-revision --statement`。

## 兼容：review_events 为新表（CREATE IF NOT EXISTS，旧库自动补建）；不进 BACKUP_TABLES（v2 归档 schema 校验保持）。

## 回归：tests/test_adjudication_contract.py 5 项（旧请求冲突/无绑定拒绝/审计事件与来源/MCP forbidden→授权后 agent 审计/撤回后不可审定）。
