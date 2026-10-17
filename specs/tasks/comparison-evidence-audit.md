# comparison-evidence-audit：比较证据治理审计（测试计划第 1 步）

来源：`out/test-plan/2026-10-17/完整竞品测试计划.md` §11.2 任务 1 与执行提示词"立即动作"。
性质：**证据治理任务**（规格状态更正 + 审计说明 + 守护测试同步），不改产品行为、不改评分器、不改历史工件。

## 目标

1. 按验收语义核对 AC-R14-01 与 M5 的 verified 状态，语义不符则更正并记录原因。
2. 对历史比较证据分级：旧 599 题检索轨结果标记为已暴露开发/回归资产，非端到端独立确认。
3. 核对依赖与当前源码绑定：复现本地基线（依赖完整环境），记录 bundle 指纹过期事实。

## 核对结论（2026-10-17 实测）

| 项 | 审计发现 | 依据 |
|---|---|---|
| AC-R14-01 验收语义 | then 子句要求"12 项点差及修正下界全部 >0，**工程底线与负例处理达标**" | specs/acceptance.json |
| 历史运行实际 | 12/12 成对下界 >0 成立；但 report.json 三指标 0.5706/0.6093/0.7834 低于底线 0.80/0.85/0.85（gate_reasons 三项 below absolute floor）；AC-R14-01.json 自述 micro_f1 0.458、负例 103/110=0.936<0.99 | out/benchmark/report.json、out/verification/AC-R14-01.json limitations |
| 状态更正 | AC-R14-01：verified → implementing；M5（其 stage）随之 verified → implementing | 本任务 |
| 轨道分级 | bundle `model=deterministic-retrieval-track`，运行器输出文件路径而非任务答案；首仓路由、单方来源截断、吞索引错误；旧 599 题确认后调参已暴露 | 计划 §1.2 P0 清单 + benchmarks/formal_run.py |
| 源码绑定 | bundle 指纹 f0786332… ≠ 审计时源指纹 458c1738…；release-check 在指纹门正确停止（exit 2） | 本次复测 /tmp 日志 + audit-summary.json |
| 依赖复现 | 默认 miniconda Python 3.13.2（含 pypdf）：make verify 135 项 OK（skip=1）；系统 3.14.4 缺 pypdf 的 2F/3E/1S 为环境差异，非源码回归 | 本任务复测 |

## 变更清单（精确 allowlist）

- `specs/progress.json`：仅 AC-R14-01.state 与 milestones.M5 两处更正（evidence 引用保留为历史工件索引）。
- `tests/test_release_gate.py`：M5 阶段断言从"应通过"改为"应拒绝且指名 AC-R14-01"（与更正后语义一致）。
- `scripts/refresh_evidence.py`：修复工件哈希回填时序——每覆写一个证据日志后立即回填，消除后续验证子进程看到"新内容配旧哈希"的不一致窗口（本次实跑暴露：--stage M5 曾因此报哈希错而非指名未完成案例）。
- `docs/benchmark-evidence-audit.md`：新增审计报告（分级、指纹、依赖、复现命令与退出码）。
- 本任务 spec/manifest 自身。

不修改：`benchmarks/evaluate.py`、`scripts/check_specs.py`、`out/benchmark/**` 全部历史工件、`out/verification/AC-R14-01.json`（保留原样，其内容即是更正依据）。禁止机械刷新旧工件哈希冒充重跑。

## 契约

- 更正后 `check_specs.py --stage M5` 必须失败并指名 AC-R14-01（不完整阶段不得冒充完成）。
- 更正后 `make verify` 必须通过（43 项 verified 案例证据经 refresh_evidence.py 对新指纹重跑绑定，非仅改哈希）。
- `make release-check` 必须继续失败（指纹过期 + M5 未完成 + 历史指标低于绝对底线，三重门均不得绕过）。
- 历史工件字节不变：bundle.json(4f4f3689…)、report.json(3ac952ad…)、TWELVE_OF_TWELVE_RESULT.json(b346caa5…)、AC-R14-01.json(5eb67a6f…)。

## 负例

1. 假 verified：将任一案例标 verified 而无当前指纹证据 → check_specs 拒绝（既有测试锁定）。
2. 越阶段：M5 含未完成案例时 `--stage M5` 必须非零（本任务更新后的 test_release_gate 锁定）。
3. 冒充重跑：仅替换 bundle 旧指纹为新值而不重跑 → release-check 的指纹门失去意义，属禁止行为（本任务不触碰 bundle）。

## 回退

单提交回滚即可恢复原状态；progress.json 历史在 git 中可追溯。审计报告与复测日志在 out/（不入库），不影响回退。

## 交付

- docs/benchmark-evidence-audit.md（审计报告）
- specs/progress.json 状态更正
- tests/test_release_gate.py 语义同步
- out/handoff.md 增量记录（不入库）
