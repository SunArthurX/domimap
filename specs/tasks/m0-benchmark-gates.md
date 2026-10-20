# m0-benchmark-gates：评分器负面测试与 release 门槛守护

- 关联：R13、R14；验收案例 **AC-R14-02**（M0）。
- 问题：评分/最终门槛的负面行为（合成包、缺系统、错分母、打平、假 ID、坏哈希不可通过）已有单元级负面测试（tests/test_benchmark_metrics.py，随基线提交），但缺少端到端的"当前仓库缺真实比较包时 release-check 必须失败"守护。
- 预期用户结果：任何人现在运行 `make release-check` 都得到非零退出与明确缺口，无法在无真实竞品运行时宣称发布通过。
- 边界：不修改评分器/检查器逻辑；只新增守护测试与证据。

## 正例 / 负例

- 正例：`tests.test_release_gate` 通过（当前状态：无 bundle → --release 非零；M1 案例 pending → --stage M1 非零）。
- 负例（AC-R14-02 证据内容，来自 test_benchmark_metrics 既有契约 + release-check 实跑）：
  - 第 6 名/相似假 ID 不算 Hit@5 命中；错误范围/编造事实丢分；重复与允许外事实不膨胀 TP。
  - 不支持却正确的说法记 FP+FN；无映射裁决无效；超时不是正确弃权。
  - 缺基线或运行 = 比较未完成；天花板打平不算胜出；合成优势不能过 release；坏工件哈希被拒；空 F1 分母 = unknown。

## 实施

1. 新增 tests/test_release_gate.py（端到端调用 check_specs --release/--stage）。
2. 运行 `python3 -B -m unittest tests.test_benchmark_metrics tests.test_release_gate -v` 与 `make release-check`（预期非零），保存日志为证据。
3. 更新 progress AC-R14-02 → verified；M0 仍为 implementing（M0.2 tiny dev 回放、M0.3 CI/安装、M0.4 接口调查未完成）。

## 验证与回退

- `make verify` 全绿；`check_specs.py --task specs/tasks/m0-benchmark-gates.json --base 99c0c26` 通过。
- 回退：删除测试文件即可；无产品行为变化。
