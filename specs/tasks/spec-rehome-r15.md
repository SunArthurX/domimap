# spec-rehome-r15 — R06 回归原义，检索反馈闭环迁册为 R15

日期：2026-10-26。依据 docs/superpowers/plans/2026-10-26-drift-analysis-and-priorities.md §2.2 与 Task 1（用户裁决路径 A：追认为正式需求）。

## 关联需求与案例

- 需求：R13（spec-driven 防偏离：需求登记必须与其原义一致，范围变更显式可见）。
- 验收案例：AC-R13-01（结构/状态诚实性——本片是其执行：改写过的需求登记归位，无"借壳"案例）。
- 任务类型：`kind: spec-change`——本片的目的就是修改规范文件，因此 manifest 列出 `specs/requirements.json` 与 `specs/acceptance.json`；不列任何兄弟 manifest。

## 问题

R06 在 docs/roadmap.md:86、:143 的定义是"依据变化定位到陈述，复核队列与反馈"（知识声明层的依赖失效与人工复核）。2026-10-26 新增的 AC-R06-03..07 描述的是"查询观测/反馈/诊断/回放/受控进化"（检索质量自我改进），与原义无关。后果：R06 标题下 7 个案例中 5 个不属于它；当前 7 个 verified 案例中 5 个来自这条新线，而原义 AC-R06-01/02 仍 implementing，注意力记账被新线主导。

## 预期用户结果

- `specs/requirements.json`：R06.cases 恢复为 `["AC-R06-01","AC-R06-02"]`；新增 `R15`「检索质量反馈与受控进化」，cases = `AC-R15-01..05`，milestones = `["M3"]`。
- `specs/acceptance.json`：AC-R06-03→AC-R15-01、04→02、05→03、06→04、07→05；`requirement` 改 `R15`；given/when/then **逐字不变**；五条连续归位（原 AC-R06-07 游离在文件末尾）；文件末尾补换行。
- `specs/progress.json`：键同步重命名；状态保持 `verified`，`evidence` 指向新建的 `out/verification/AC-R15-0N.json`（`case_id` 已更新，命令/环境/工件照抄），旧文件路径加入 `historical_evidence`；随后 `scripts/refresh_evidence.py` 重跑五案例命令对齐指纹（真实重验，不是改哈希）。
- `docs/roadmap.md`：:102 "21 项需求、44 个案例"→"22 项需求、49 个案例"；§5 表 R14 行后新增 R15 行。

## 边界

- 不改任何产品代码、测试行为、benchmark 协议、release-check 行为。
- 不改五条案例的文本语义；不改其他 42 个案例状态。
- 若用户后续选择路径 B（降为实验），本片回滚即可，再另起 experiments 附录任务。

## Given/When/Then

- 正例：Given 现 R06 含 7 案例 / When 执行本片 / Then `tests.test_spec_contracts.test_r06_keeps_original_scope_and_r15_hosts_retrieval_feedback` 通过；`make spec-check` 报 `requirements: 22, acceptance_cases: 49, verified_cases: 7`。
- 负例：任何 AC-R06-03..07 残留 → 测试失败；R15 五案例不连续 → 测试失败；进度键与证据 `case_id` 不一致 → `check_specs.validate` 拒绝（"Evidence mismatch"）。

## 文件与有序任务

1. tests/test_spec_contracts.py 新增测试（先红）。
2. 本 manifest + 本文件。
3. 三个规范 JSON 改写（脚本化，保持 indent=2 / ensure_ascii=False）。
4. docs/roadmap.md 两处。
5. out/verification/AC-R15-0N.json 由旧文件派生（case_id 更新）。
6. `python3 -B scripts/refresh_evidence.py spec-rehome-r15 b868a42` 两遍 → `make verify`。

## 验证

见 manifest `verification`。

## 回滚

见 manifest `rollback`。

## 遗留

- R06 原义的实现接线（record_baseline/scan_dependencies 无生产调用）属 Task 11，不在本片。

## 连带一致性（执行中发现，纳入本片）

- 12 份历史任务 manifest（drift-correction-c1..c7、retrieval-observation/feedback/diagnosis/evolution-pilot/evolution-replay）的 `acceptance_cases` 与 `requirements` 已同步改为 AC-R15-0N / R15，使其 `--task` 验证命令继续可执行；它们的 `.md` 叙述中出现的 "R06" 指迁册前的归属，作为历史记录保留原文。
- `tests/test_drift_correction.py:23` 守账用例与四个测试模块的 docstring 同步改用新 ID。
- `scripts/check_specs.py:22` 显式需求集加入 R15（精确相等守卫保留，期望集 21→22）；`specs/product.md:13` 增加 R15 一句并重申 R06 原义。
