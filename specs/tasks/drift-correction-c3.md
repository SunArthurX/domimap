# drift-correction-c3 — 反馈与统计契约纠正（F07）

依据 out/drift-audit-2026-10-26 C3。日期：2026-10-26。案例：AC-R06-04（贡献纠正，最终收敛见 C7）。

## 修复（tests/test_feedback.py 新增 5 项 + 旧契约 3 项更新）

- 幂等摘要覆盖完整规范化 payload（含 reason/expected_evidence）：同键异 reason=conflict
  （probes: feedback_reason_conflict）。
- 同来源修订需 expected_revision（乐观并发）：缺失/不符拒绝；同 payload=duplicate；
  不同来源为并行意见不互斥（probes: same_source_conflict）。CLI --expected-revision、
  UI 冲突 409。
- 统计（probes: ai_suggestion_changes_human_rate / replay_pollutes_user_unknown）：
  人工样本选用时间只看权威来源——AI 建议不再改变采哪条人工判定；unknown/覆盖率/
  未反馈只用用户 profile 分母（replay/诊断事件不污染）；分来源命中率
  hit_rate_by_source；metric_definitions 冻结口径说明（correct_refusal 明示为
  refusal-precision，独立应拒答集准确率需独立标注另行统计）。

## 验证

python3 -B -m unittest tests.test_feedback -v（24/24）。

## 回滚

revert feedback.py/__main__.py/ui.py 本片差异；无数据迁移。

## 文件

domimap/feedback.py、domimap/__main__.py、domimap/ui.py、tests/test_feedback.py、
specs/tasks/drift-correction-c3.{json,md}。
