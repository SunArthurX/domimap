# drift-correction-c4 — 诊断状态机、簇身份与 AI 执行边界（F05/F06）

依据 out/drift-audit-2026-10-26 C4。日期：2026-10-26。案例：AC-R06-05（贡献纠正，最终收敛见 C7）。

## 修复（tests/test_diagnosis.py 新增 9 项，先失败后通过）

- 簇身份（F06）：键 = 查询摘要 + domain 范围 + 事件版本（_cluster_key）——跨范围/
  跨版本不归并；partial 反馈入队；再裁决（改判 hit/正确拒答）自动移出并清空簇；
  空工作区 list_issues 返回 []（_connect 改用完整闭环 schema）。
- 历史一致性（F06）：diagnose 比对事件版本与当前 collect_version（图 mtime/size/
  节点数/seeds 摘要/知识代际）；不一致时重跑发现标 current_retest_ 前缀、相关假设
  降为 unruled 并进 unknowns——当前重测只构成假设依据。
- 池实证（F06）：top50 之外不再断言"召回/分路"——_pool_probe 直接核查词法召回池
  成员资格，区分 in_pool_not_ranked（排序/分路/去重）与 not_in_pool（召回）。
- 补充查询（F06）：query_text 覆写与原摘要不同 → query_text_override 记入 facts 并
  计入 input_digest（新输入，不冒充原查询）。
- AI 状态机（F05）：ai_attempts 表 (cluster, ai_input, attempt) 原子占用——并发同输入
  只调一次模型（另一方 in_progress，无 IntegrityError）；规则诊断缓存 reused 不阻断
  显式 use_ai；非法/空输出 → invalid_response（不标 ok、不生成 proposal）；失败簇级
  冷却 300s、至多 AI_MAX_ATTEMPTS=2；无 key → unavailable 不占额度（配置后可重试）；
  AI 输入摘要含规则摘要+模型名+客户端注入标志。

## 验证

python3 -B -m unittest tests.test_diagnosis -v（23/23）；全闭环 109/109。

## 回滚

revert diagnosis.py 本片差异；ai_attempts 表可 DROP。

## 文件

domimap/diagnosis.py、tests/test_diagnosis.py、specs/tasks/drift-correction-c4.{json,md}。
