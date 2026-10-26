# workspace-restore — R07：整库导出/恢复（证据+代+图+来源登记+知识库）

日期：2026-10-26。依据 docs/superpowers/plans/2026-10-26-drift-analysis-and-priorities.md Task 7；production-readiness P0 第四项。

## 关联需求与案例

- R07：导出恢复与知识互操作。
- AC-R07-01（运行中的知识库与固定证据 → 在线备份并在干净目录恢复 → 正文/修订/审定/范围/引用完整且可检索）；AC-R07-03（归档路径穿越/链接与遗忘 → 恢复/清理不越界、效果可解释）。

## 问题

既有 `KnowledgeStore.backup/restore` 只覆盖 knowledge.db 表；证据 blob、不可变代、graph.json、来源 manifest 不随包——干净目录恢复后笔记的 `ev:` 引用悬空，active 代记录的是发布时绝对路径，移动/恢复到别处即不可定位。

## 预期用户结果

- `domimap export-workspace WS DEST [--include-queries]`：DEST 不存在；暂存目录内写入 store.db 快照、graph.json、coverage.json、blobs/*、gens/*、`<label>/manifest.json`、knowledge/（kbackup v2）、可选 queries.db；`workspace-manifest.json`（schema domimap.workspace.v1）记逐文件 sha256、components、counts、active 代 sha、`contains_query_log`；整体 rename 发布。
- `domimap restore-workspace ARCHIVE TARGET`：TARGET 不存在；逐成员校验（绝对路径/`..`/反斜杠拒绝、符号链接拒绝、越界拒绝、缺件拒绝、sha 不符拒绝）；知识库经 `KnowledgeStore.restore` 校验进入 knowledge.db；证据库 active 代可定位且 graph.json sha==active；全部通过后 rename；失败不留目标与暂存。
- `EvidenceStore._gen_path`：代文件绝对路径不存在时按本库旁 gens/ 同名文件定位。
- 隐私：queries.db 默认不随包；显式带上时清单标注且 CLI 打印"勿公开发布"。

## Given/When/Then

- 正例：build + 一条笔记两次修订 → export → restore 到空目录 → 同 ev_id 读到同文本、节点集合一致、active 代可定位、笔记 revision=2 且 history 两条、来源 manifest 一份、summary.knowledge.notes=1。
- 负例：目标已存在（含无关文件）→ FileExistsError 且目标不变；篡改 blob → "sha256" 错误、无目标、无暂存残留；删 store.db → "missing"；清单加 `../escape.json` → "path"；成员换成符号链接 → "symlink"；export 到已存在目录 → FileExistsError；queries.db 仅 `include_queries=True` 才带且标注。CLI：exit 4（已存在）/5（校验失败）。

## 设计选择

- 目录包而非 zip：可直接检视、逐文件哈希、与既有 kbackup v2 目录格式一致；zip 可作后续薄封装。
- 复用 `KnowledgeStore.backup/restore` 的校验与原子发布，不复制其逻辑。
- 来源 manifest 原样随包（root 为导出机绝对路径）：异机恢复后用 `domimap rebind` 指向新路径再 update——身份不变。

## 验证 / 回滚

见 manifest。636 tests OK（含 8 项新测试）。

## 遗留

- R07-02：Markdown/Obsidian 显式导入的冲突预览（`preview_import`）与导出目录回灌防护（T12）。
