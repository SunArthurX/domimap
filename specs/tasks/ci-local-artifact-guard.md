# ci-local-artifact-guard — 守账测试跳过本地工件缺失环境（CI/新克隆）

日期：2026-10-27。CI 首跑暴露：tests/test_drift_correction.py 断言 out/drift-audit-2026-10-26、out/dev-ws、out/verification 本地工件存在——这些不入 git，新克隆/CI 必失败（与 test_release_gate 的既有 skipTest 模式一致）。

## 修复

setUp 检查 `out/drift-audit-2026-10-26/correction` 与 `out/dev-ws`，缺失即 skipTest（本地存在时全量断言不变）。另：AC-R13-01 的 evidence 指回 `out/verification/AC-R13-01.json`（refresh_evidence 维护的标准文件；batch-reverify 曾指向 rerun 目录副本，指纹错位）。

## 验证

本地 `python3 -B -m unittest tests.test_drift_correction -v`（4 项全过，工件在）；CI 将走 skip 分支。
