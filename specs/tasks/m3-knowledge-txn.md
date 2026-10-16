# m3-knowledge-txn：单条知识与 claims 的 SQLite 短事务（M3.1，目标 AC-R05-01）

- 契约：submit(body, claims, expected_revision, idempotency_key)——
  ①新知识→revision 1；②同幂等键同内容→返回原结果（幂等，不新建）；③同键不同内容→ConflictError；
  ④amend 携旧 expected_revision→ConflictError 防覆盖；携当前值→revision+1 且历史全留；
  ⑤withdraw 撤回→状态 withdrawn、历史可读；⑥事务中断（failpoint）→无半行、库可用；
  ⑦并发多键→全部落库；并发同键同内容→恰一行。
- claims：类型 requirement/implementation/observation/decision/inference，各带 statement/evidence/scope/state；
  推断被接受也不改 EXTRACTED 性质（accepted≠extracted，状态与类型分列）。
- CLI/UI/MCP 写入口与复核队列在 M3.2-3.4；本片为事务核心。
