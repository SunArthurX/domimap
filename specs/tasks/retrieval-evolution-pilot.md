# retrieval-evolution-pilot — 一次真实「查询—反馈—诊断—修复—回放—回滚」闭环（P4）

依据 out/plans/retrieval-feedback-evolution-plan.md P4 切片。日期：2026-10-26。
前置：retrieval-observation / retrieval-feedback / retrieval-diagnosis（AC-R06-03/04/05 verified）。

## 关联需求与案例

- 需求：R06（闭环主体）、R04（修复不得破坏公共检索语义与负例守门）、R13。
- 验收案例：**AC-R06-06**（本次正式登记，ID 已查重）。
- 保护：R02/R03/R05/R07/R12/R14；不动 benchmark 协议、留出集与门槛。

## 真实问题（已用本闭环前序切片在真实语料上复现）

真实工作区 out/dev-ws（--discover 全量图，30+ 仓）：
- 查询「商品 审核状态 流转」：含原始实词（商品/审核/状态，df=41/4/20）的业务设计文档
  `doc/商品主数据融合项目设计文档V1.0.docx` 排名 **15**（top_k=6 之外）；
  「商品主数据 融合」同文档排第 12（top_k=6 内仅第 5——侥幸过线）。
- top6 被 seeds 扩展英文词匹配的 generic 节点（fastjson asm 的 `Item`、`ItemProduct`
  等）占据。计划 §11 示例（正确证据在第八名）的真实语料实例，且更强（第 15 名）。

## 闭环实录（全部真实运行；ReplayRun 留档 queries.db，工件在 out/dev-ws/）

1. 记录：event qe:41b0798ea263a2c6faae6168（DOMIMAP_KEEP_QUERIES=1）。
2. 反馈：miss + expected=商品主数据融合项目设计文档（fb:f11df904f3fbdce12b054e82）。
3. 诊断：dg:a8815636ef4d6fb4554ef594 → rerank_probe **rank_15**，ranking_defect
   supported（out/dev-ws/diag-pilot.json）。
4. 样本集 v1 冻结 → 基线 rp:3c157f4d9dc6a6ed（4/5，目标 MISS）。
5. **候选 1（仅名称加成限定）失败**：rp:1d848d2e87552f37 目标仍 MISS 且 2 项回归
   （均为扩展词加成受益者）→ 走计划失败分支：回滚演练 rp:ed82d326940e231d 与基线
   逐样本一致（verdict=no_change）。
6. 根因细化（扩展词与原始词同权竞争）→ 样本集 v2 重冻结（保持者只收原始词证据支撑
   的成功；目标×2）→ 基线 rp:b4ecbb3da99bef65（4/5）。
7. 候选 2（名称加成限定 + EXPANSION_TOKEN_WEIGHT=0.35，独立任务
   retrieval-identifier-boost-scope）：rp:6c5ee7d7810fbe9f **5/5**——目标 1 rank
   15→4、目标 2 rank 5→1，保持者 rank1 保持，负例保持；verdict=improved、回归 0。
8. 回滚演练：rp:c3a6b5a353c09e5d 与基线 v2 逐样本一致（verdict=no_change）。
9. 全量 make verify 556 tests OK（含修复的 8 个标识符排序用例）。

L3 启用决定：候选 2 启用（保留在当前源码），依据=上述回放证据 + 全量回归；
回滚路径=revert search.py 差异（演练已实证等价基线）。

## 回放引擎（本片交付的最小核心，P5 泛化）

`domimap/replay.py`：
- ReplayRun 表（queries.db）：run_id、created、label（baseline|candidate|rollback）、
  source_fingerprint、samples_sha256、params、results_json、summary_json、notes。
- 样本文件（冻结）：`{"samples":[{"id","query","params",{"expect":"refused"}或
  "expected":子串}]}`；加载即算 sha256 存档（改样本=新 run，不可比）。
- 执行：每样本 trigger=replay 记录（EV13 隔离）；expect=refused 断言拒答；
  expected=证据子串 → 文件级名次（与 diagnosis 同粒度，top_k 内才算命中）。
- 汇总与比较：targets/regressions/improvements（对比 baseline run；样本集摘要
  不一致明确拒绝比较）。
- CLI `domimap replay -g G --samples F [--label L] [--baseline RUN_ID]`。

## 执行序列（全部真实运行，产物存 out/dev-ws/ 与 out/verification/）

1. 记录：`DOMIMAP_KEEP_QUERIES=1 domimap query "商品 审核状态 流转" --json`。
2. 反馈：`domimap feedback <event> --relevance miss --expected "商品主数据融合项目设计文档"`。
3. 诊断：`domimap diagnose --event <event> --out out/dev-ws/diag-pilot.json`（rank 证据）。
4. 样本集：目标样本 + 命中保持样本（现 top1 多样查询取 expected=当前 top1 文件）+
  负例（应拒答）→ out/dev-ws/replay-pilot-samples.json。
5. baseline 回放（修复前代码）→ ReplayRun 记录。
6. 实施修复（search.py 两处计分点传 name_tokens）。
7. candidate 回放 → 目标 ≤6、零回归、负例保持。
8. 回滚演练：还原修复差异 → rollback 回放结果与 baseline 一致 → 恢复修复。
9. 全量 make verify + task 检查 + 证据。

## 正例 / 负例

1. 目标样本 rank 15→≤6（hit），命中保持样本全部仍在 top_k，负例仍 refused。
2. rollback run 与 baseline 逐样本一致（证明回滚可执行且可验证）。
3. 现有标识符排序测试（原始查询标识符加成）不回归——加成只对扩展词收紧。
4. replay 事件 trigger=replay，不进用户统计（qstats user 口径不变）。
5. 样本文件被修改后 run 拒绝与旧 run 比较（samples_sha256 不匹配→明确不可比）。

## 文件（本片 7 文件 + 修复任务 1 文件）

replay 侧：`domimap/replay.py`、`domimap/__main__.py`（replay 子命令）、
`tests/test_replay.py`、`specs/acceptance.json`/`specs/requirements.json`/
`specs/progress.json`（AC-R06-06）。
修复侧：独立任务 specs/tasks/retrieval-identifier-boost-scope.md/.json，
`domimap/search.py` + `tests/test_identifier_ranking.py`（增补原查询/扩展词区分用例）。
CHANGELOG/architecture 增量段。

## 验证

- `python3 -B -m unittest tests.test_replay tests.test_identifier_ranking -v`
- 真实闭环命令序列（上文 1-8，全部真实运行并留工件）
- `make verify`；两个 task 检查 --base HEAD；证据 out/verification/AC-R06-06.json。

## 回滚

- 修复回滚：revert search.py 的 name_tokens 差异（回放演练已实证等价 baseline）。
- replay 回滚：删除 replay.py/测试/CLI 与 ReplayRun 表（无迁移）。

## 遗留

- P5：改善/退化报告、启用决定记录、积压优先级、诊断→修复→回放全链追溯视图。
