# retrieval-feedback — 反馈修订、历史列表、分组统计与受控删除（P2）

依据 out/plans/retrieval-feedback-evolution-plan.md P2 切片。日期：2026-10-26。前置：retrieval-observation（AC-R06-03 已 verified）。

## 关联需求与案例

- 需求：R06（反馈闭环主体）、R01（统计如实：unknown 不算 miss、判定来源分列、不合并口径）、
  R13（spec-driven）、F2（人工入口可用反馈与历史）。
- 验收案例：**AC-R06-04**（本次正式登记，ID 已查重）。
- 保护：R02/R03/R05/R07/R08/R14 与既有案例；不触碰检索行为与正式 benchmark。

## 问题与用户结果

P1 只留下"发生了什么"；没有"结果好不好"。本片后用户可以：对任一次查询提交
hit/partial/miss（证据相关性）与任务结果（success/failure/correct_abstention/
needs_clarification），带理由与可选预期证据；修正走追加修订保留历史；查看按时间/
入口/状态/原因过滤的历史与完整链路；看到分组统计（含判定覆盖率与未反馈比例）；
受控删除与备份恢复；导出成功/失败开发样例（P4 回放输入）。

## 命中口径（冻结，勿改）

- 相关性 relevance ∈ unknown|hit|partial|miss|not_applicable；任务结果 task_outcome ∈
  unknown|success|failure|correct_abstention|needs_clarification。**有返回候选绝不自动
  算 hit；unknown 不算 miss；partial 不折算成 hit。**
- 判定来源 source ∈ user_feedback|human_annotation|dev_gold|rule_check|ai_suggestion，
  各自单独统计，不合并成一个正确率；AI 自评分只能是 ai_suggestion，永不覆盖人源。
- 事件的有效相关性（统计用）＝同事件权威来源（user_feedback/human_annotation/dev_gold）
  最新修订的一致值；权威来源互相矛盾 → disputed（该事件只计覆盖率不计命中率）；
  无权威来源 → unknown。rule_check/ai_suggestion 不改变有效值。
- 已判定完整命中率 = H/(H+P+M)（仅取有效相关性；分母不含 unknown/not_applicable/
  disputed）；effective.unknown = 无权威判定的 profile 数（与未反馈比例同口径，呈现用）；
  同时报告判定覆盖率与 partial 单列。
- 正确拒答比例 = refused 事件中被权威判为 correct_abstention 的占比（分母=有权威
  反馈的 refused 事件）；"系统拒答"本身不是正确标签。
- trigger≠user（retry/replay/diagnostic）的事件彻底与用户口径分离（EV13）：用户命中率/
  有效相关性只统计含 user 触发事件的 profile；无 user 事件的 profile（回放/开发评测）
  单列 non_user_effective，不并入。
- 同 query_digest+params 的重复出现只算一次样本（导出与命中率去重，重复次数另列）。

## 数据契约（queries.db 追加表，无破坏迁移）

```
feedback(
  feedback_id TEXT PRIMARY KEY,     -- "fb:"+sha256(idempotency 内容)[:24]
  event_id TEXT NOT NULL,
  revision INTEGER NOT NULL,        -- 同 (event_id) 内追加递增，从 1 起
  relevance TEXT NOT NULL,
  task_outcome TEXT NOT NULL,
  source TEXT NOT NULL,
  reason TEXT,                      -- 本地保留；导出时截断
  expected_evidence TEXT,           -- 可选：预期节点 id/ev_id/路径
  created REAL NOT NULL,
  idempotency_key TEXT UNIQUE,
  content_digest TEXT NOT NULL,
  superseded_by TEXT,               -- 被新修订指向；历史不删
  UNIQUE(event_id, revision))
```

修订规则：同 source 的再次提交 = 追加 revision+1 并把旧修订 superseded_by 指向新
（幂等键相同且内容相同 → duplicate 不新增）；不同 source 并存不覆盖。并发提交用
(event_id, revision) 唯一键 + 事务串行：冲突方重读后追加（无丢修订）。写入中断 =
单事务原子（无半行）。

删除与恢复：delete_events(ids|before|all) 同事务删事件及其派生 feedback（返回计数，
先显式 snapshot 才允许 all）；snapshot(path) 用 SQLite backup API 出一致性快照；
restore(path) 校验 obs 表结构后原子替换（tmp+rename），替换失败保留原库。外部副本
的删除限制如实说明（本片只管本工作区文件）。

导出：export_samples(kind=success|failure) → H 或 M 的去重样例（query_text 存在才
可回放，否则 replayable=false；带 digest/params/version/预期证据/理由截断/出现次数），
由调用方写入 out/ 下文件；不含密钥与完整源码。

## 设计选择

- **feedback 表放 queries.db 而非新库**：反馈与事件同一因果链（外键式 event_id），
  删除/快照/恢复需要一致边界；与权威知识库仍分库（product.md 第 5 条不受影响）。
  较简单方案"知识库里存反馈"会让 AI 建议混入审定语义——不足取。
- **有效相关性解析放查询时而非物化**：修订/争议/来源优先级是派生视图，物化会在
  追加修订时引入更新路径与不一致窗口。
- **source 优先级**：user_feedback=human_annotation=dev_gold（权威，互相矛盾即
  disputed）> rule_check > ai_suggestion（仅参考，永不改有效值）——plan §3"最后一条
  AI 意见不得静默覆盖用户或独立标注"的直接实现。

## 正例 / 负例 / 并发

1. G 命中事件；W 用户标 hit+success 带理由；T 修订 1 落库，effective=hit，
   命中率 1/1，覆盖率 1/事件数。
2. G 同事件用户改标 miss；T 追加修订 2，修订 1 superseded 但仍可读，effective=miss。
3. G 无任何反馈；W 统计；T relevance=unknown 不进命中率分母，未反馈比例如实。
4. G 用户标 miss 后 ai_suggestion 标 hit；T ai 修订并存、effective 仍 miss；
   按来源统计里 ai_suggestion 单列 hit。
5. G 用户标 hit、human_annotation 标 miss；T disputed=1，该事件不计入命中率。
6. G refused 事件被标 not_applicable+correct_abstention；T 正确拒答比例计入；
   另一 refused 无反馈 → 只进分母不计分子（如实）。
7. G retry/replay 事件带反馈；T 用户统计不含它们（EV13），单独可查。
8. G 同 query_digest+params 出现 3 次、1 次反馈 miss；T 导出 1 个样例、occurrences=3。
9. W 同幂等键同内容重投；T duplicate，修订数不变。W 同键异内容；T conflict 标记、
   原修订不动。
10. W 未 snapshot 直接 delete_events(all)；T 拒绝（要求先备份）；snapshot 后删除成功、
    计数如实；restore 后事件与反馈完整回来；restore 损坏文件 → 拒绝且原库未动。
11. W 8 线程并发对同事件提交修订；T 全部落库、revision 连续无重复无丢失。
12. G query_text 未保留（隐私默认）；W 导出失败样例；T 样例 replayable=false，不伪造
    可回放。

## 文件与顺序（本片 8 文件）

`domimap/feedback.py`（新：FeedbackStore+服务 API）、`domimap/observation.py`
（store 暴露连接复用给 feedback 表建表与写入；或由 feedback.py 自建——实现取自建短
连接，避免跨模块持锁）、`domimap/__main__.py`（feedback/history/qstats/qexport 四个
子命令）、`domimap/ui.py`（POST /api/feedback、GET /api/history、GET
/api/feedback/stats + 结果区反馈条 + 历史/统计工作流）、`tests/test_feedback.py`（新）、
`specs/acceptance.json`+`specs/requirements.json`+`specs/progress.json`（AC-R06-04）。
顺序：① spec/registry → ② feedback.py + 单测 → ③ CLI → ④ UI API+前端 → ⑤ 全量
验证与证据。

MCP 反馈工具留 P3（与诊断入口一并评估），UI/CLI 已覆盖人工反馈面——边界如实登记。

## 验证

- `python3 -B -m unittest tests.test_feedback -v`
- `python3 -B -m unittest tests.test_observation tests.test_ui_workbench
   tests.test_refusal_reason -v`
- `make verify`；`python3 -B scripts/check_specs.py --task
   specs/tasks/retrieval-feedback.json --base HEAD`
- 证据：out/verification/AC-R06-04.json。

## 文件登记说明

同 retrieval-observation：manifest 另登记并行未提交任务脏文件，仅为全 diff 范围
检查（AC-R13-01），不归本片成果。

## 回滚

删除 domimap/feedback.py、tests/test_feedback.py；revert __main__.py/ui.py 本片差异；
registry 移除 AC-R06-04。数据：feedback 表可整体 DROP（observations 事件不受影响）；
备份/快照文件在 out/ 由用户处置。

## 遗留缺口

- AI 诊断与规则预检（P3）、回放与启用（P4/P5）、MCP 反馈工具（P3）。
- 争议反馈的人工裁决 UI（当前以 disputed 状态呈现，裁决走再提交修订）。
