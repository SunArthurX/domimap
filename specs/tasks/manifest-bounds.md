# manifest-bounds — 任务 manifest 边界恢复（R13）

日期：2026-10-26。依据 docs/superpowers/plans/2026-10-26-drift-analysis-and-priorities.md §2.4 与 Task 3（执行时细化见该节）。

## 关联需求与案例

- R13（spec-driven 防偏离：`--task` 的"实际 Git 变更是否超出允许文件"检查必须有效）。
- AC-R13-01（结构诚实性：越界改动检查失败——本片让该检查重新有牙）。
- 任务类型 `spec-change`：改检查器（scripts/）、测试、模板与 workflow 文字、20 份历史 manifest 的 files；不含 `domimap/` 产品代码。

## 问题

14 份 manifest（drift-correction-c0..c7、retrieval-×6）共用同一份 79 文件清单，包含 `specs/requirements.json`/`specs/acceptance.json` 与全部兄弟 manifest；另 6 份历史 manifest 也列有并行兄弟条目。`check_specs.check_task` 的 `changed ⊆ files` 判定对这些任务恒真，"bounded slice"失去约束力。规避理由（为并行未提交文件做全 diff 检查）在 T0 入库后已不存在。

## 预期用户结果

- `check_specs.check_manifest_bounds(name, task)`：按 `kind` 约束——`slice`（默认）不得列 NORMATIVE_SPECS（product/requirements/acceptance/benchmark/workflow/protocol）或其他任务 manifest；`spec-change` 可列二者但不得含 `domimap/` 文件；`umbrella` 须非空 `reason`；未知 kind 拒绝。
- `--task` 模式与全量结构校验（`make spec-check`/`--structural`）都执行该检查；仓库内每份 manifest 必须通过（仓库级测试）。
- 20 份 manifest 按各自 `.md`「## 文件」节裁剪：c0 → spec-change（跨任务状态纠正）；publish-openprep×2 → umbrella（发布前跨任务文档净化，写明理由）；其余 → 本片文件 + own json/md + test_files。

## Given/When/Then

- 正例：Given slice 只列本片文件 / When check / Then 通过；Given spec-change 列 acceptance.json+兄弟 manifest / Then 通过。
- 负例：slice 列 acceptance.json → "normative"；slice 列兄弟 manifest → "task manifests"；spec-change 列 domimap/x.py → "product code"；umbrella 无 reason → "reason"；kind=whatever → "kind"；真实仓库任一 manifest 违规 → 仓库级测试 subTest 失败并点名。

## 文件与有序任务

1. tests/test_spec_contracts.py：契约测试 + check_task 接入测试 + 仓库级测试（先红，20 份点名）。
2. scripts/check_specs.py：NORMATIVE_SPECS/TASK_KINDS/check_manifest_bounds；check_task 调用；main() 全量循环。
3. 裁剪 20 份 manifest（脚本化，保留其他键与 .md 原文）。
4. specs/task-template.json 增 `kind`；specs/workflow.md §2 一句说明；CHANGELOG；计划文档细化说明。

## 验证 / 回滚

见 manifest。

## 遗留

- 被裁剪的历史 manifest 其 `verification` 中的 `--task … --base HEAD` 在干净工作树上恒通过（无变更），属预期；它们的真实范围证据以当时的 .md 与提交为准。
