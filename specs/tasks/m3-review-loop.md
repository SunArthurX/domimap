# m3-review-loop：依赖失效到 claim 级待复核 + 确认绑定新证据（M3.3，目标 AC-R06-01/02）

- API：`scan_dependencies(current {证据键: sha})`——与基线比对，仅受影响 claim 入队（按 note/claim 粒度，不整篇串用）；重复扫描同摘要不重复入队（主键去重）。
- `confirm_review(note_id, idx, new_evidence, new_sha)`——确认必须绑定新证据摘要（claim_bindings 表），点击/使用频率不刷新真实性；`touch_note`（使用计数）显式不改复核状态；撤回后不入队。
- 队列提供差异（old/new sha）与处理动作（confirm/amend/withdraw）。
