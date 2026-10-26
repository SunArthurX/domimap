# retrieval-evolution-replay — 通用回放、启用记录与闭环追溯（P5）

依据 out/plans/retrieval-feedback-evolution-plan.md P5 切片。日期：2026-10-26。
前置：P1–P4（AC-R06-03/04/05/06）。

## 关联需求与案例

- 需求：R06（闭环收口）、R13。
- 验收案例：**AC-R06-07**（正式登记，ID 已查重）。
- 保护：R12/R14——业务统计与正式 benchmark 分离；正式验收仍走 make release-check。

## 交付

1. **改进启用记录**（queries.db `improvements` 表）：improvement_id、cluster_id、
   diagnosis_id、baseline_run/candidate_run/rollback_run、decision
   （activated|rejected|rolled_back）、decided_at、source_fingerprint、notes。
   记录时可校验三 run 样本集摘要一致且 candidate 对 baseline 判定为 improved
   （不满足即拒绝记录——启用必须有回放依据）。
2. **闭环追溯视图**：`chain(cluster_id)` → 簇 + 用户事件（含被反馈的那条原始查询）
   + 反馈修订历史 + 诊断列表（含 rank 证据）+ 回放 run 链（label/指纹/verdict）
   + 启用决定。CLI `domimap evolution -g G [--cluster X] [--json]` 输出；
   `--record-improvement` 登记启用/拒绝/回滚。
3. **积压优先级**：list_issues 按（未诊断优先 → event_count 降序 → last_seen 降序）
   排序，积压可见。
4. 真实数据收口：把 pilot 的启用决定登记进 out/dev-ws（候选 2 activated），导出
   追溯链工件 out/dev-ws/evolution-trace.json 作为 AC-R06-07 证据之一。

## 正例 / 负例

1. G pilot 的 run 链与诊断；W 记录 improvement(activated)；T 链视图从原始事件
   qe:… 一路到 candidate run 与启用决定完整可读。
2. W 以非 improved 的 run 对登记 activated；T 拒绝（无回放依据不得启用）。
3. W 三个 run 样本集摘要不一致时登记；T 拒绝。
4. G 两个未诊断簇（事件数 3 与 1）；W list_issues；W 事件多者在前、已诊断者靠后
   （积压优先级）。
5. 生产阶段与正式比较不受影响：release-check 仍按原规范失败（不因本片改变）。

## 文件（本片 5 文件）

`domimap/replay.py`（improvements 表 + record_improvement + chain + verdict 链）、
`domimap/diagnosis.py`（list_issues 排序）、`domimap/__main__.py`（evolution 子命令）、
`tests/test_evolution_replay.py`（增补追溯/启用/积压用例）、
`specs/acceptance.json`+`specs/requirements.json`+`specs/progress.json`（AC-R06-07）。
CHANGELOG/architecture 增量段。

## 验证

- `python3 -B -m unittest tests.test_evolution_replay -v`
- 真实数据：`domimap evolution -g out/dev-ws/graph.json --record-improvement …`
  与 `--cluster ic:… --json` 导出 out/dev-ws/evolution-trace.json
- `make verify`；task 检查 --base HEAD；证据 out/verification/AC-R06-07.json。

## 回滚

删除 improvements 表与 evolution CLI/视图；replay.py 其余能力不受影响。

## 遗留

- 簇解决后的事件级再验证（修复后用户复问的自动比对）依赖真实使用流量，留后续。
- 正式四竞品比较与 M0–M5 验收不在本计划内。
