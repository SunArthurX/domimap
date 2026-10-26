# knowledge-entries — R05/R07：知识层写入口三入口可达、存在性检查、冲突预览、导出页回灌防护

日期：2026-10-26。依据 docs/superpowers/plans/2026-10-26-drift-analysis-and-priorities.md Task 12。

## 关联需求与案例

- R05（保存/修订/审定/撤回、冲突/幂等、再次检索）；R07（Markdown 互操作与导入）。
- AC-R05-01（并发/重复提交、旧 expected_revision、中断 → 保存/重试/撤回/读取历史 → 事务、幂等与冲突正确——此处补齐"撤回/读取历史"的操作面与冲突感知）；AC-R07-02（外部修改的导出页 → 显式导入及冲突提交 → 稳定 ID/base_revision 生效，导出不回灌为独立证据）。

## 问题（漂移审计 §2.3/§3 R05·R07 行）

amend/withdraw/accept/history/backup/restore/export/import 只有库函数（UI 仅 submit、CLI/MCP 无）；withdraw/accept 对不存在 ID 静默成功；无冲突预览；导出目录可被当普通文档摄入。

## 预期用户结果

- CLI：`note submit --body --claims --idempotency-key | amend NOTE --body --expected-revision | withdraw NOTE | accept NOTE --idx | get NOTE | history NOTE`；`kb export DIR | import FILE [--preview] | backup DIR | restore ARCHIVE DEST`。退出码：invalid_params 2、not_found/exists 4、conflict 5、unavailable 6。
- MCP：`kg_note {action∈submit|amend|withdraw|accept, …}` ∈ WRITE_TOOLS（默认不公布、未启用调用 write_disabled）；冲突/校验失败以 `{"error","code"}` JSON 返回。
- 服务：`AppService.note_submit/amend/withdraw/accept/get/history`、`kb_export/import/backup/restore`，`ServiceError` code 增 `conflict`/`exists`。
- 知识库：`withdraw` 仅对 active 生效、否则 ConflictError 并返回 `{status: withdrawn}`；`accept_claim` 不存在 → ConflictError（只改 state，不改类型）；`preview_import(path)` 返回 note_id/exists/file_revision/current_revision/revisions_ahead/conflict/current_body/file_body/claims，不写库；`_parse_export` 共用。
- 扫描：`_is_knowledge_export(raw)`（前 2KB 的 front-matter 含 note_id+base_revision）→ 不捕获、不建节点、coverage 注明"不回灌"。

## Given/When/Then

- 正例：CLI 全生命周期（submit→amend→history 2 条→accept→get state=accepted→withdraw）；kb export→改文件→import --preview conflict=false→import revision=2→backup→restore 到新路径；MCP 启用后 submit/amend/withdraw，提交的 inference 陈述 state=proposed。
- 负例：withdraw/accept 未知 ID → ConflictError；二次 withdraw → ConflictError；amend 旧修订号 → exit 5；get 未知 → exit 4；kb restore 已存在目标 → exit 4；MCP 未启用 → write_disabled；action 枚举外 → invalid params；库内先改后导入 → preview conflict=true、import ConflictError；导出页放进仓再 build → 无节点、无 sources 行、coverage 含"回灌"。

## 设计选择

- 写入口全部经 AppService：UI/CLI/MCP 同一校验与错误码；MCP 写沿用 `--enable-write` 单一开关。
- 导出页在捕获前识别并跳过：既不建节点也不固化 blob，彻底避免"导出即证据"。

## 验证 / 回滚

见 manifest。664 tests OK（含 6 项新测试；一处旧测试的宽松撤回语义改为断言冲突）。

## 遗留

- UI 的 amend/withdraw/accept/recheck-confirm 写面（UI 工作台任务）；Obsidian wikilink 展示。
