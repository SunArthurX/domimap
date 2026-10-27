# concurrent-diagnosis-row — 并发同簇诊断撞主键读回复用（CI ubuntu-3.9 实跑暴露）

日期：2026-10-27。CI run 40457165180 唯一失败：`test_concurrent_ai_single_call_no_exception` 得到 `['IntegrityError','ok']`。

## 关联需求与案例

- R15 / AC-R15-05（诊断并发契约：并发同输入只调一次模型、无 IntegrityError——C4 曾修复 ai_attempts 层，本缺陷在上一层 diagnoses 行）。

## 根因

`diagnoses.diagnosis_id = "dg:"+sha256(cluster_id+input_digest)` 确定性相同；并发同簇同输入诊断时两线程的 existing SELECT 都未命中（对方未提交），后到 INSERT 撞 PRIMARY KEY——该 INSERT 无 IntegrityError 守卫，异常直接冒出 diagnose()。本地 40 次未复现（线程时序），CI ubuntu-3.9 复现。

## 修复

`diagnosis.py`：INSERT diagnoses 的 `with db` 包 try/except IntegrityError → 重读该行 → `status="reused"` 复用；行不存在才 re-raise。与 ai_attempts 层同语义。

## 回归

`test_concurrent_diagnosis_row_conflict_reads_back_reused`：包装连接在首次 INSERT diagnoses 前先替"另一线程"写入同 ID 行再抛 IntegrityError，确定性触发；断言 `status=="reused"`、`ai_status=="none"`，无异常冒出。
