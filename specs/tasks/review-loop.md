# review-loop — R06 原义 + F4-02：依据变化 → 定位陈述 → 待复核队列 → 检索面陈旧标记 → 显式确认

日期：2026-10-26。依据 docs/superpowers/plans/2026-10-26-drift-analysis-and-priorities.md Task 11（R06 回归原义后的首个实现切片）。

## 关联需求与案例

- R06（依据变化定位到陈述，复核队列与反馈）；F4（版本复核约束）。
- AC-R06-01（一篇笔记两个陈述仅一条依据变化 → 扫描变化与重复更新 → 只产生相关待复核项且不重复，提供差异和处理动作）；AC-R06-02（已处理复核项与负反馈 → 修改/确认/撤回后再次搜索 → 状态与证据一致；点击和频率不变成真实性证明）；AC-F4-02（已复核知识的依据内容或范围改变 → 旧审定不继承新版本）。

## 问题（漂移审计 §2.2/§3）

机制只在库里：`record_baseline/scan_dependencies/confirm_review` 仅测试调用；`attach_if_present` 恒不传 `current_digests`，`stale` 永不计算；`amend` 清空 claims 却留下按 idx 的旧绑定。且在不可变 ev_id 模型下，"同一 ev_id 的 sha 变化"根本不会发生——需要重定义：依据已变 = 同一来源出现更新版本。

## 预期用户结果

- `EvidenceStore.review_digests()` → `cited`（ev_id→自身 blob sha）、`current`（ev_id/sid→来源最新 blob sha）、`latest`（ev_id→最新 ev_id）。
- `batch.refresh_reviews(out_dir, store)` 在 `publish_generation` 后运行：`record_baseline(cited, overwrite=False)`（引用版本即基线）→ `scan_dependencies(current, latest_keys)` → 仅受影响陈述入 `review_pending`（PK 去重），`new_evkey` 记录可绑定的新证据。
- 检索面：`attach_if_present` 传 `current`；`_claim_stale` = 在队列中或绑定版本≠当前；`_render` 标 `[stale:N 条陈述待复核]`；UI 种子 `stale:true`。点击（touch_note）与重建不改变。
- 确认：`AppService.confirm_review(note_id, idx)` → 引用替换为最新 ev_id、`claim_bindings` 绑定其 sha、队列移除；CLI `recheck list|confirm`（不存在项 exit 4）；UI `GET /api/recheck`。
- `amend(claims=...)` 事务内清理该笔记的 `claim_bindings` 与 `review_pending`。
- 兼容：`review_pending.new_evkey` 进 SCHEMA（新库原生）、旧库 `__init__` ALTER 补列、旧 v2 归档（6 列）恢复时按 legacy 形状放行。

## Given/When/Then

- 正例：两陈述分引 PRD/checklist 证据 → 改 PRD → update → 队列恰 1 项（note#0，old≠new，new_evidence 为 ev:）；重复 update/强制重建不增项；检索 Knowledge 候选 claims[0].stale、claims[1] 不 stale、文本含 stale；touch + 重建后仍 stale；confirm 后队列空、不 stale、引用含新 ev_id。笔记在最后一次构建之后创建、随后改源 → 仍被检出（引用版本即基线）。amend 后该笔记绑定/待复核清零。CLI recheck list 含 note_id 与陈述原文；confirm 后 list 显示"无待复核"。
- 负例：confirm 不存在的 idx → 非零退出；无变化不入队。

## 设计选择

- 基线取"引用时版本"而非"上次扫描版本"：否则笔记创建于两次构建之间会漏检；且 ev_id 不可变天然给出该版本。
- 构建期写 knowledge.db 仅限 baselines/review_pending（机器派生的复核簿记），不触碰正文/修订/审定。

## 验证 / 回滚

见 manifest。658 tests OK（含 5 项新测试）。

## 遗留

- 删除的来源（sid 不再出现于新代）尚未作为"依据消失"入队——需比对代内来源集合（后续切片）。
- 变化摘要（diff 文本）未提供，队列只给 old/new sha 与新 ev_id；UI 复核确认写入口随 T12。
