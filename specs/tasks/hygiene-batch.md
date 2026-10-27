# hygiene-batch — 漂移审计 §5 卫生清单批处理

日期：2026-10-26。依据 docs/superpowers/plans/2026-10-26-drift-analysis-and-priorities.md Task 15 / §5。

## 关联需求与案例（贡献）

- R08（AC-R08-02：查询日志按用户数据处理——gitignore 全局兜底 + 导出勿发布提示）；R10（AC-R10-01 的"诊断可用"侧——doctor 数据库健康段；格式版本守卫 user_version）；R11（AC-R11-02：Actions 钉 SHA、CI 矩阵覆盖 requires-python 下限）。三项案例整体仍 implementing，本片只关闭对应卫生项。

## 内容

1. `storage.ensure_user_version(db, expected, label)` + `STORE/KNOWLEDGE/QUERIES_DB_VERSION=1`：三库 `__init__` 打标；高于当前 → ValueError 拒绝打开（新版本写的库不猜）。
2. `domimap doctor`：图旁三库的 存在性 / `PRAGMA quick_check` / user_version / active 代（store）/笔记数（knowledge）/事件数（queries）。
3. `store._decode_evidence`：utf-8 严格 → gb18030 宽容（GBK 来源证据读回不乱码，与扫描层一致）。
4. `scenario_req`：领域词表扩展改走 `s.query(text, seeds=seeds)`（EXPANSION_TOKEN_WEIGHT 降权）；卡片仍展示扩展词来源。
5. `.gitignore`：`queries.db` / `queries.db-*` / `queries.key` 全局（任意 `-g` 工作区位置都不入库）。
6. `qexport` / `diagnose --out`：内容含查询原文时 stderr 打印"勿公开发布（roadmap §9）"。
7. Actions 钉提交 SHA（带原 tag 注释）：checkout 11d5960a / setup-python a26af69b / upload-artifact ea165f8d / download-artifact d3f86a10 / pypi-publish 7245906f（release/v1 分支头）。
8. CI python 矩阵 `["3.9","3.11","3.13"]`（pyproject >=3.9 下限入测）。
9. 计数/文案：ui.py docstring 8+6；tests/test_ui_workbench WORKFLOW_NAMES 补"反馈与历史"；CHANGELOG 空重复标题移除。
   （roadmap 44→49、production-readiness 六工具、__main__ 6 工具等已在 T1/T2 各自更新。）

## Given/When/Then

- 正例：三库 user_version==1；手改高版本 → 打开报 "newer domimap"；doctor 输出三库 quick_check=ok/active/notes/events；gb18030 文件证据读回含中文；scenario_req 调 `s.query` 的 text 为原查询且 kw 含 seeds；gitignore 含三模式；KEEP_QUERIES 下 qexport stderr 含"勿公开"；两个 workflow 的 uses 全为 40 位 SHA 且矩阵含 "3.9"；docstring 计数与表一致。
- 负例：CI 用例断言非 SHA 的 uses 失败；`### 已实现

### 已实现` 不再出现。

## 验证 / 回滚

见 manifest。686 tests OK（含 9 项新测试）。

## 遗留

- benchmarks/TWELVE_OF_TWELVE_RESULT.json 文件名语义夸大：被 docs/benchmark-evidence-audit.md 等引用，且本项目纪律保持 `git diff benchmarks/` 为空——本轮不动 benchmarks/，留待下次正式比较时重命名并更新引用。
- requires-python 3.9/3.10 的 Windows 矩阵、`PRAGMA user_version` 的真实迁移路径（未来格式变更时）。
