# 比较证据治理审计（comparison-evidence-audit）

日期：2026-10-17。执行：测试计划 `out/test-plan/2026-10-17/完整竞品测试计划.md` 第 1 步（§11.2 任务 1）。
审计基线：Git `a474583`，源指纹 `458c173868206e824821242e07d05e5e0b42f2e21995b8e08d1e2ea246f80eac`（与同目录 audit-summary.json 一致）。

本任务只做证据治理：更正与验收语义不符的 verified 状态、给历史证据分级、复现本地基线。不修改产品代码、评分器、协议或任何历史运行工件。

## 1. 本地基线复现（本次实测）

| 命令 | 环境 | 结果 | 退出码 |
|---|---|---|---|
| `make verify` | miniconda Python 3.13.2（含 pypdf） | 135 项 OK（skip=1：bundle 已存在时 release 无包护栏按设计跳过） | 0 |
| `make release-check` | 同上 | `Comparison incomplete/invalid: Missing/stale domimap source fingerprint`，在统计前停止 | 2 |
| 计划预检 `make verify` | 系统 Python 3.14.4（缺 pypdf） | 2 failures、3 errors、1 skipped | 2 |

结论：预检的 5 项失败/错误全部为环境依赖差异（默认 3.14.4 无 pypdf），非源码回归；依赖完整环境（3.13.2）下 135 项全绿可复现。复现 PDF 契约应使用安装了声明文档依赖的隔离解释器，不修改全局环境。

## 2. R14/M5 状态更正（核心更正）

AC-R14-01 验收语义（specs/acceptance.json）：**"12 项点差及修正下界全部 >0，工程底线与负例处理达标"**——工程底线即 protocol 的 Hit@5 ≥0.80、Accuracy ≥0.85、micro-F1 ≥0.85、负例 ≥0.99。

历史运行实际：

| 来源 | hit@5 | accuracy | micro_f1 | 负例 | 12 项成对 |
|---|---|---|---|---|---|
| out/benchmark/report.json（evaluate.py 对 bundle 计算） | 0.5706 | 0.6093 | 0.7834 | 1.000 | —（gate_reasons：三项 below absolute floor） |
| out/verification/AC-R14-01.json limitations（DEV 级分析口径） | 0.644 | 0.644 | 0.458 | 103/110=0.936 | 12/12 下界 >0 |

两处口径数字不一致本身即是审计发现（多报告分数不一致，计划 §1.2 P1 项）。无论取哪组：**绝对底线与负例底线均未达标**，且该证据自身 limitations 已承认种子为确定性单次记录、裁决为模型辅助盲化（无人工终审）。

更正：

- `specs/progress.json`：AC-R14-01 `verified → implementing`；里程碑 M5（其 stage）随之 `verified → implementing`。
- evidence 引用保留为历史工件索引（非 verified 状态下仅作参考，不构成完成证据）。
- `tests/test_release_gate.py` 的 M5 阶段断言同步更正为"必须拒绝且指名 AC-R14-01"——不完整阶段不得冒充完成。
- 未修改 AC-R14-01 的证据文件本体：其内容（limitations 自述未达标）正是本次更正的依据。

按 AGENTS 规则，verified 必须与验收语义一致；结构检查通过（当时 12/12 断言命令退出 0）不等于产品验收完成。

## 3. 历史证据分级

旧 599 题 × 5 系统比较资产统一分级为：**已暴露的开发/回归资产（deterministic retrieval track），非端到端独立确认证据**。保留原样用于防回归与复现，不得再作为最终留出或"当前源码端到端分数"引用。

| # | 发现 | 依据 | 分级影响 |
|---|---|---|---|
| 1 | bundle `common.model=deterministic-retrieval-track`；formal_run.py 主要输出文件路径 | out/benchmark/bundle.json、benchmarks/formal_run.py | 检索轨 ≠ 主轨 Agent 任务；路径不能证明任务正确率 |
| 2 | 多仓题路由 `family.split('+')[0]`（首仓），使用评测内部来源标签 | formal_run.py 路由逻辑 | 对手难以完成跨仓任务；比较条件不公平 |
| 3 | claude-obsidian 适配：来源平铺 Markdown、单族 ≤800 页、单文件 <400KB、关 rerank | 适配器配置 | 单方来源截断，非其原生知识工作流 |
| 4 | 建索引异常被忽略；若干适配器用正则从展示文本抽路径 | 适配器代码 | 环境故障可能被误计为产品失败 |
| 5 | Git 历史显示查看确认结果后修改检索再在同批重跑 | git log（M5 改进轮） | 旧 599 题已参与调参，失去留出用途 |
| 6 | gold-questions.json 及标签位于开发可读区 | out/benchmark/gold-questions.json | 仅路径出库不构成隔离 |
| 7 | 70 个 cluster 中 41 个为多族组合；真实独立族 28 | bundle cluster 统计 | 组合不等于独立样本，置信区间可能过窄 |
| 8 | 五 seed 记录内容完全相同，无独立会话证据 | bundle records | 不证明五次独立执行 |
| 9 | 每系统三份报告/任务说明分数状态不一致 | 本文档 §2 两行对照 | 运行先后与版本链不可还原 |

## 4. 源码绑定与依赖

- bundle 源码指纹 `f0786332d946e7a2…`（创建于 2026-10-17 03:11）早于终态提交 `a474583` 的规格/文档定稿，与审计时源指纹 `458c1738…` 不一致；`make release-check` 在指纹门正确停止。
- 纪律：指纹覆盖文件变更后必须重新执行验证再产证据，禁止机械替换旧哈希（本任务未触碰 bundle）。
- 历史工件字节冻结记录（本次审计时 SHA-256 前 16 位）：bundle.json `4f4f3689d42398a5`、report.json `3ac952adbf9b1715`、TWELVE_OF_TWELVE_RESULT.json `b346caa5e5b4b38a`、AC-R14-01.json `5eb67a6f6cd08ab7`、gold-questions.json `d91d497e75565f7a`。

## 5. 更正后的诚实状态

- 44 项验收案例：43 verified + AC-R14-01 implementing；里程碑 M0–M4 verified、M5 implementing。
- `make verify`：135 项全绿（含更正后的 M5 拒绝护栏）。
- `make release-check`：继续失败（指纹过期 → M5 未完成 → 历史指标低于绝对底线），符合"缺真实证据必须失败"的规则。
- R14 12/12 成对结果保留为检索轨历史成绩；最终验收仍需：五方原生适配的端到端主轨、真实独立确认集、独立裁决与绝对底线达标（测试计划十步的第 2–10 步）。

## 6. 下一步

按计划顺序：`comparison-native-adapters`（五方原生适配 + 每适配器 ≥20 个 dev 契约样例）→ 数据隔离 → 40 题五方全链试跑。
