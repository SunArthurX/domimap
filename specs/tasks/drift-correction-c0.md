# drift-correction-c0 — 纠正完成状态并保存审计基线

依据 out/drift-audit-2026-10-26/audit-and-correction-plan.md C0。日期：2026-10-26。

## 关联需求与案例

- 需求：R13（spec-driven 防偏离：不得在证据失效时维持 verified 声明）。
- 验收案例：AC-R13-01（结构/状态诚实性——本片即其执行：受影响声明降级并留因）。

## 做了什么（全部已执行）

1. **归档基线**（不动历史证据）：
   - out/drift-audit-2026-10-26/correction/baseline-handoff-2026-10-26.md（纠正前交接原文）；
   - baseline-working-tree.patch（纠正起始全部未提交差异）、baseline-untracked.txt；
   - baseline-real-workspace-artifacts.sha256（真实工作区样例/诊断/追溯工件哈希）。
   - 未删除/改写 out/dev-ws/queries.db、queries.key 与任何历史证据文件。
2. **状态纠正**：specs/progress.json 中 AC-R06-03..05 → implementing（F06/F09/F01、F01/F07/F08、F05/F06）；AC-R06-06/07 → implementing（F02/F03/F04）。六任务 manifest state → implementing。历史 evidence 文件保留可读，不做哈希刷新。
3. **activated 失效记录**：out/dev-ws/activation-ccf1ee268b695abbf2cd-invalidated.json——按 F02/F03/F04 声明 imp:ccf1ee268b695abbf2cd 失效待复核；DB 原行保留不动；排序策略（name_tokens 限定 + EXPANSION_TOKEN_WEIGHT）留在代码中作为**未证实候选**，按 C7 重新证明或停用（只回退该精确差异，不整文件回退 search.py）。
4. **文档纠偏**：docs/architecture.md 与 CHANGELOG.md 中"全部完成/已启用/零回归"声明改为"已实现骨架 + 待纠正范围"的准确表述。

## 不做

- 不动其他任务/案例状态（无新的直接失效依据）。
- 不重置 M0–M5；不触碰 benchmark 协议与 release-check 行为。

## 验证

- python3 -B scripts/check_specs.py（结构通过；受影响案例不再声称 verified）。
- python3 -B scripts/check_specs.py --task specs/tasks/drift-correction-c0.json --base HEAD。

## 回滚

本片为状态/文档纠正：还原 progress.json 六条与任务 state、删除失效记录 JSON 与归档目录即可；无代码/数据迁移。

## 文件

specs/progress.json、六个既有任务 json（state 字段）、docs/architecture.md、CHANGELOG.md、
specs/tasks/drift-correction-c0.{json,md}；归档与失效记录在 out/（不入 manifest 范围检查）。
manifest 另登记并行未提交任务与本闭环全部文件，仅为全 diff 范围检查（AC-R13-01）。
