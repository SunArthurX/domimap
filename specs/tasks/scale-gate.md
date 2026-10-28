# scale-gate — 合成 200 仓门禁

日期：2026-10-28。计划 T13。

## 问题

没有一个会失败的检查来回答「仓的数量上去之后，建图和查询还在不在预算里」。

## 预期

- `scripts/scale_gate.py` 生成 N 个单类仓库，建图，记建图秒数、graph.json 字节、一次查询秒数。
- 任一数字超过 `SYNTHETIC_BUDGETS` 时退出码 1。
- 单元测试：超预算的假报告被拒绝；4 仓实建在预算内。
- 200 仓实跑结果写入 `out/verification/scale-synthetic-200.json`，并在 `docs/production-readiness.md` 标明这是合成语料，不是 ERP。

## 负例

- 把 graph_bytes 设成比预算大 1，`check` 必须返回违规。

## 回滚

删除脚本和测试。不改图格式。
