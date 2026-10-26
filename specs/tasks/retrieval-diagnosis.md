# retrieval-diagnosis — 问题簇、规则预检、诊断包与可选模型分析（P3）

依据 out/plans/retrieval-feedback-evolution-plan.md P3 切片。日期：2026-10-26。前置：retrieval-observation / retrieval-feedback（AC-R06-03/04 verified）。

## 关联需求与案例

- 需求：R06（诊断半边）、R01（根因有依据或明确未知，不编造）、R08（预算/注入边界）、
  R13（spec-driven）。
- 验收案例：**AC-R06-05**（本次正式登记，ID 已查重）。
- 保护：R02/R03/R05/R07/R12/R14 与既有案例；诊断不改检索行为、不自动改知识。

## 问题与用户结果

P2 之后能记录"哪些问题没找到"；本片回答"为什么"。用户可以：把 miss/失败/异常查询
归并为问题簇；对簇运行确定性规则预检（预期证据是否在图、诊断性重跑定位召回/排序
差距、拒答原因映射）；得到结构化诊断包（可导出交给 coding agent）；可选地用已配置
模型做一次有预算的根因分析（无模型时规则诊断与导出照常）；生成改进任务提案草稿。

## 边界

- 诊断只读图与记录库；**不改检索代码、不写知识库、不联网（除显式 --ai 的模型调用）**。
- 诊断性重跑以 trigger_kind=diagnostic + parent_event_id 记录（不污染用户统计）；
  重跑用确定性核心（BM25 主路径，关 semantic/rerank/embed 可选层）。
- 正确拒答（not_applicable/correct_abstention）不进诊断队列（负例保护）。
- AI 分析首版每簇一次、异常最多一次有限重试；相同输入+版本复用已有诊断；冷却期内
  失败不重试；无 key/模型 → ai_status=unavailable，规则诊断不受影响。
- 诊断包/提示中源码片段、查询与资料均为数据（非指令）；模型输出只按白名单字段解析，
  不执行、不直接入知识（提案只是草稿）。

## 数据契约（queries.db 追加表）

```
issue_clusters(cluster_id TEXT PRIMARY KEY,   -- ic:<digest 前 16>
  query_digest TEXT NOT NULL, query_len INTEGER, first_seen REAL, last_seen REAL,
  event_count INTEGER NOT NULL, status TEXT NOT NULL)  -- open|diagnosed
cluster_events(cluster_id TEXT, event_id TEXT, PRIMARY KEY(cluster_id, event_id))
diagnoses(diagnosis_id TEXT PRIMARY KEY,      -- dg:<sha256[:24]>
  cluster_id TEXT NOT NULL, event_id TEXT, created REAL,
  input_digest TEXT NOT NULL,                 -- 簇+图版本+期望证据 → 复用判定
  pack_json TEXT NOT NULL,                    -- 结构化诊断包（facts/findings/hypotheses/unknowns）
  ai_status TEXT,                             -- none|unavailable|ok|error
  ai_json TEXT,                               -- 模型输出白名单字段+usage
  proposal_json TEXT)                         -- 任务提案草稿（白名单字段）
```

归并规则：relevance=miss 或 task_outcome=failure 或 status=error 的 user 触发事件按
query_digest 入簇（非 user 事件的反馈按 plan 留在开发评测口径，不入用户问题队列）；
effective disputed 不入簇（先裁决）。

规则预检（确定性，全部带可核对依据）：
1. `expected_resolution`：feedback.expected_evidence → 图节点 id / ev: 证据（经
   evidence_map 反解 rel）/ 名称或路径子串（≤200 命中取词法最高分）。解析不到 →
   finding `expected_not_in_graph`（来源未覆盖或期望写错，两个假设都列，不武断）。
2. `rerank_probe`：以原查询+原 domain 重跑 top_k=50（diagnostic 记录）。期望证据
   rank ≤ 原 top_k → `presented_but_marked_miss`（呈现/客户端问题，检索层成绩保留）；
   rank ≤ 50 → `ranking_gap`（附 rank 与两侧候选 id）；未进 top 50 → `recall_gap`。
3. `refusal_mapping`：refused 事件按 refusal_reason 映射假设——domain_filter_empty →
   范围问题（不偷偷放宽）；coverage_below_min/generic_only → 表达不匹配或资料缺失；
   identifier_absent → 来源未覆盖或标识符不存在；no_strong_candidate → 弱信号。
4. `error_mapping`：status=error → 技术队列（result.error 类名）。
5. `coverage_snapshot`：图规模、files_scanned、skipped 原因计数（来自事件 coverage）。

诊断包（pack_json）：diagnosis_id、cluster_id、event_id、created、facts（上述）、
findings[]（check/result/evidence）、hypotheses[]（cause/status∈supported|unruled|
unknown/support 摘要）、unknowns[]、budget 用量。AI 输出白名单字段：
root_causes[]（cause/confidence∈low|medium|high/supporting_facts/unruled）、
recommended_actions[]（bounded text）、open_questions[]；超白名单字段丢弃并记录
`dropped_fields`。

AI 预算（首版冻结）：每簇 1 次调用；输入字符上限 8000（诊断包截断表示）；输出
max_tokens 1500；超时走 LlmClient 默认（DOMIMAP_LLM_TIMEOUT，120s）；冷却 300s
（失败后）；同 input_digest 复用不重复计费。token/费用用量记 ai_json.usage。

任务提案草稿（proposal_json）：title、root_cause、allowed_files=[]（由人/coding
agent 填）、expected_gain、negative_cases、verification、rollback——全部来自包内
依据；状态不是任务 manifest（沿用仓库契约，plan §7）。

## 正例 / 负例 / 并发

1. G 用户标 miss 且期望证据在图中 rank 8（top_k=6）；W 诊断；T finding ranking_gap
   附 rank=8 与候选 id；诊断性重跑事件 trigger=diagnostic、parent 指向原事件；用户
   统计不变（EV04）。
2. G 期望证据不在图中；W 诊断；T expected_not_in_graph，假设列表同时含"来源未覆盖"
   与"期望写错"，unknowns 非空（EV04 反例：不武断）。
3. G 期望证据已在原 top_k 内却被标 miss；W 诊断；T presented_but_marked_miss
   （客户端/呈现问题，不归因检索算法）。
4. G domain_filter_empty 拒答被标 miss；W 诊断；T 范围问题假设 + 原参数 domain 值
   如实呈现，不放宽（EV05）。
5. G 正确拒答（not_applicable+correct_abstention）；W 归并；T 不入簇。
6. G 无 key；W diagnose --ai；T ai_status=unavailable、规则 findings 完整、退出码 0
   （EV06：无模型仍可用）。
7. G 注入查询文本（"忽略以上指令…"）；W 打包 + AI；T 查询文本以数据段呈现于提示，
   模型输出多余字段被丢弃（dropped_fields 记录），无任何执行（EV09）。
8. G 同簇同输入二次 diagnose --ai；T 复用首次诊断（调用计数 1、无第二次计费）。
9. G 并发两进程 diagnose 同簇；T input_digest 相同时后到者复用先到者记录（幂等）。

## 文件与顺序（本片 6 文件）

`domimap/diagnosis.py`（新）、`domimap/__main__.py`（issues/diagnose 子命令）、
`domimap/ui.py`（GET /api/issues + 反馈页问题簇区块，只读）、
`tests/test_diagnosis.py`（新）、`specs/acceptance.json`+`specs/requirements.json`+
`specs/progress.json`（AC-R06-05）。CHANGELOG/architecture 增量段（同片）。
顺序：① spec/registry → ② diagnosis.py + 单测 → ③ CLI → ④ UI 只读区块 → ⑤ 验证。

## 验证

- `python3 -B -m unittest tests.test_diagnosis -v`
- `python3 -B -m unittest tests.test_feedback tests.test_observation -v`
- `make verify`；task 检查 --base HEAD；证据 out/verification/AC-R06-05.json。

## 文件登记说明

同前两片：manifest 另登记并行未提交任务与本闭环前两片的全部文件，仅为全 diff 范围
检查（AC-R13-01）。

## 回滚

删除 domimap/diagnosis.py、tests/test_diagnosis.py；revert __main__.py/ui.py 差异；
registry 移除 AC-R06-05；三张诊断表可 DROP（事件与反馈不受影响）。

## 遗留缺口

- P4 真实修复闭环、P5 通用回放与启用记录；MCP 诊断工具；簇优先级排序（P5 积压）。
- 解析/索引缺陷的深度核查（重扫对比）需要 build 工具配合，留 P5 按需。
