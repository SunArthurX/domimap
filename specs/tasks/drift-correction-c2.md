# drift-correction-c2 — 事件身份、版本与幂等（F06/F09）

依据 out/drift-audit-2026-10-26 C2。日期：2026-10-26。案例：AC-R06-03（贡献纠正，最终收敛见 C7）。

## 修复（tests/test_observation.py 新增 5 项先失败后通过）

- 请求身份摘要排除 duration_ms（F09 探针 retry_idempotency）：耗时噪声不得决定
  两次请求是否相同；不同逻辑输入（top_k）仍为 conflict。
- 有效参数解析入档：params_json 记录合并查询签名默认（top_k/expand/min_cov/budget）
  后的实际生效值。
- 版本完整（F06）：version_json 增 knowledge 代际（mtime/size，缺失=unknown）与
  seeds.json sha256（策略/词表指纹）；不伪造可复现性。
- 工作区密钥并发（F09）：O_CREAT|O_EXCL 唯一赢家，输家读赢家（≤2s 重试），0600。
- 记录延迟上界（F09）：观测库锁等待 1s × 至多 3 次（≈3s 上界，常量
  RECORD_LATENCY_BOUND_S=4.0 文档化）；被独占时 fail-open 有界返回 recording_failed，
  查询照常。

## 验证

`python3 -B -m unittest tests.test_observation -v`（32/32）。

## 回滚

revert observation.py 本片差异；无数据迁移。

## 文件

domimap/observation.py、tests/test_observation.py、specs/tasks/drift-correction-c2.{json,md}。
