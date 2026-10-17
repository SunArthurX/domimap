# comparison-diagnostic-runner：诊断轨批量运行器（测试计划 §11.2 任务 3 的确定性部分）

来源：计划 §11.2 任务 3（comparison-agent-runner）、§5（冻结预算、执行与故障政策）。
性质：**评测基础设施**。主轨（真实 Agent 会话、模型、工具轨迹）阻塞于模型凭据，
本任务先交付诊断轨的批量执行与记录契约；主轨扩展点在接口上预留。

## 修复的旧缺陷（formal_run.py）

| 旧缺陷 | 新运行器 |
|---|---|
| 五 seed 记录内容完全相同、无独立执行证据 | 每次 (system, question, repeat) 独立 run_id/起止时间/原始工件/错误分类；确定性系统输出可相同但记录独立（protocol 限制如实记录） |
| 单次覆写运行文件 | 运行目录 out/diagnostic-runs/<batch_id>/，追加不覆盖 |
| 无预算/耗时记账 | 每记录 secs；批次汇总 per-system 耗时/错误分类计数 |
| 无交错 | 系统顺序按题交错（round-robin），避免一个系统独占 |

## 设计

`benchmarks/runners/diagnostic_runner.py`：
- 输入：questions JSON（`{questions:[{id, category, query}]}`，**无 gold 字段**——评分输入另行）；gold 绝不进入运行器。
- 适配器：benchmarks/adapters（防 gold 路由签名已由契约测试锁定）。
- repeats：协议 [11,23,37,53,71]，逐 repeat 独立记录；确定性系统的相同输出如实保留，`seed_note` 说明。
- 输出：run-manifest.json（batch_id/UTC/各系统版本证据/指纹/问题集哈希/适配器 prepare 报告）+ records/<system>/<repeat>.jsonl（逐题 QueryRecord.to_dict + question category 回填）+ summary.json（错误分类矩阵、耗时）。
- 预算：query_timeout/prepare_timeout 透传适配器；超时记录为 timeout 不重试不删题。
- 故障：env 缺失 → 该系统 skip 并在 manifest 记 reason（不算零分）；产品错误保留在分母。

## 契约（测试，合成小题集 + domimap 适配器实跑）

1. 记录数 = 系统 × 题 × 重复，一次不多一次不少。
2. 每个 record 有独立 run_id、ISO 起止、error_class 合法、raw 工件存在。
3. 重复间输出可相同但 run_id 不同。
4. 交错：相邻 record 的 system 不同（>1 系统时）。
5. gold 字段进入 questions 输入 → 运行器拒绝（防泄漏负例）。
6. env 缺失系统 → manifest.skipped 有 reason，无该系统 records。
7. 追加语义：同 batch 重跑不覆盖既有文件（新 batch_id）。

## 回退

单提交回滚；out/diagnostic-runs 为生成物。
