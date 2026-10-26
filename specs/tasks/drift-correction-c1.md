# drift-correction-c1 — 恢复与遗忘的数据风险修复（F01/F08）

依据 out/drift-audit-2026-10-26/audit-and-correction-plan.md C1。日期：2026-10-26。

## 关联需求与案例

- 需求：R06、R01（失败保留原库、删除不留断链残迹）。
- 验收案例：AC-R06-04（恢复/删除语义属其范围；本片为纠正贡献，最终 verified 在 C7 后统一收敛）。

## 修复内容（探针转测试先行：tests/test_feedback_lifecycle.py 10 项先失败后修复）

F01 恢复（feedback.py）：
- `_validate_backup`：独立只读连接完整校验——integrity_check、期望表集合精确相等
  （未知表/缺表拒绝）、逐表列结构比对（对内存参考库 `_loop_schema_sql()` 生成，
  FeedbackStore 现在负责创建全部闭环表）、九组父子引用断链检查（cluster_events/
  feedback/diagnoses→events、diagnoses→clusters、improvements→runs/clusters）、
  2GiB 大小上限。任何失败在触碰原库之前抛出。
- `restore`：校验通过后先拒绝符号链接目标；`BEGIN EXCLUSIVE`（250ms 短超时单次，
  被占用即拒绝在线原地恢复）→ checkpoint 后按字节复制安全副本
  `<db>.pre-restore-<ts>` → 备份字节写入唯一 tmp 并 fsync → 释放事务、关闭连接、
  清理 -wal/-shm → `os.replace` 原子发布 → 重开并复验；复验失败自动从安全副本回退。
  失败路径（校验/占用/IO）均不触碰原库。不再使用 `Connection.backup`（源连接持
  事务时死锁，实测修复）。
- `FeedbackStore` 成为 queries.db 基座：初始化即建全部闭环表（events/feedback/
  idempotency_conflicts/簇/诊断/回放/改进），恢复校验与删除清理依赖完整 schema。

F08 删除与裁剪（feedback.py / observation.py）：
- `delete_events`：ids/before 模式同步删除 feedback、cluster_events、该事件的
  diagnoses（含 pack_json 中的查询原文）、空簇及其孤儿诊断；事件属于 improvements
  引用的簇时**拒绝删除并点名**（固定证据链保护）。delete_all（须出示备份）清空
  events/feedback/簇/诊断/improvements，保留自包含 replay_runs 并在返回中说明。
- 容量裁剪（observation.record）：有 feedback/簇关联/诊断的事件豁免裁剪（固定证据
  不毁坏），仅裁未判定观察且不产生孤儿派生行。

## 反例（全部为正式测试）

坏列结构/未知表/断链引用/损坏文件/目标符号链接/活动连接占用（拒绝且原库完整）；
成功恢复留安全副本；删除后无诊断原文/簇关联/孤儿反馈残留；固定证据拒绝删除；
delete_all 后六表为空且 runs 保留；裁剪保护已判定事件。

## 验证

- `python3 -B -m unittest tests.test_feedback_lifecycle -v`（11/11）
- `python3 -B -m unittest tests.test_feedback tests.test_observation
  tests.test_diagnosis tests.test_evolution_replay -v`（71/71）

## 回滚

revert feedback.py / observation.py 本片差异；数据无迁移（新表为 IF NOT EXISTS）。

## 文件

domimap/feedback.py、domimap/observation.py、tests/test_feedback_lifecycle.py、
specs/tasks/drift-correction-c1.{json,md}；manifest 另登记并行与本闭环全部文件
（仅为全 diff 范围检查）。
