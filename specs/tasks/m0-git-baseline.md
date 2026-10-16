# m0-git-baseline：Git 基线、治理文件与首个证据闭环

- 关联：R11（开源与分发交付，M0 部分）、R13（Spec-driven 防偏离）；验收案例 **AC-R13-01**。
- 问题：仓库无版本管理，task/base diff 检查无法对真实 Git 运行；缺许可证、安全/贡献/变更说明与缺陷登记，公开底线不成立。
- 预期用户结果：干净 checkout 可重复验证；故意越界/孤儿/假 verified 被检查器拒绝；已知产品缺陷有登记与复现命令。
- 边界：本任务不做产品行为变更、不做 CI（后续 m0-install-ci）、不修复已知缺陷（M1+ 按任务修）。

## 前置与契约

- 前置：specs/requirements/acceptance/progress 与 scripts/check_specs.py 已存在并通过 `make verify`（45 测试）。
- 版本管理契约：首次提交包含当前全部受管源文件；`out/`、`dist/`、`__pycache__` 由 .gitignore 排除，用户资料不入库（此前已做业务数据清除，2026-10-16 记录）。
- 许可契约：MIT，版权归属 "domimap contributors"；不虚构作者姓名/联系方式；第三方清单只登记真实依赖（无 vendored 代码）。

## 正例 / 负例

- 正例：`make verify` 通过；`check_specs.py --task specs/tasks/m0-git-baseline.json --base <首次提交>` 通过（改动均在允许文件内）。
- 负例（AC-R13-01 证据内容）：
  1. 在任务范围外新增文件后运行 task 检查 → 必须失败并列出越界文件；
  2. progress 中把无证据案例标 verified → `--stage M0`/结构检查必须拒绝；
  3. 需求清单删除任一显式需求 → 结构检查必须失败。

## 实施步骤

1. 创建 LICENSE、SECURITY.md、CHANGELOG.md、CONTRIBUTING.md、THIRD_PARTY_NOTICES.md、docs/known-defects.md（缺陷登记含复现命令，M1+ 修复任务引用）。
2. `git init` + 本仓库局部身份配置（GitHub noreply 形式，不虚构邮箱）+ 首次提交（受管文件全量）。
3. 执行本任务文件变更 → `make verify` → task/base diff 检查。
4. 生成 AC-R13-01 证据：依次运行正例与三个负例，捕获命令、退出码、输出工件（`out/verification/`），写入 progress。
5. 提交任务变更；更新 out/handoff.md。

## 验证与回退

- 命令：`make verify`；`python3 -B scripts/check_specs.py --task specs/tasks/m0-git-baseline.json --base <ref>`；`python3 -B scripts/check_specs.py --stage M0`（本任务后仍应失败于 AC-R14-02 未验证，属预期）。
- 回退：任务仅新增文件与受管元数据，`git revert` 即可；无数据迁移。

## 结果记录（实现后填写）

- 见 progress.json `AC-R13-01` 证据与 out/verification/ 工件。
