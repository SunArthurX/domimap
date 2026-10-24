# clean-code-pass：第一性原理清理——删除死物，不动需求

- 关联：R13（AC-R13-01 任务纪律）。验证工具与代码卫生清理，不改任何产品行为。
- 来源：用户 2026-10-24 指示——clean code 思想过一遍项目，推送前删除/排除不必要的功能或文件。
- 红线：AGENTS.md 禁止悄悄削减需求（四客户端、人工 UI、persona、时效、知识维护、平台恢复、四竞品质量门全部保留）。

## 方法（可复现）

1. 全量反向引用分析：`git ls-files` 每个文件按 basename + py-import 形式统计全仓引用（排除入口/规范/测试/任务清单）。
2. AST 级死代码：未使用 import（import 名在文件内出现 ≤1 次）；零引用公开函数（含同文件接线排除 cmd_* 误报，逐个词干级复核）。
3. 判据：删除必须"全仓零引用 + 非需求载体"；有据保留项写入本 spec 备查。

## 删除（全仓零引用实证）

- `benchmarks/ELEVEN_OF_TWELVE_RESULT.json`：早期试点结果快照（11/12），被 12/12 版取代，词干级引用 0。
- `benchmarks/bootstrap_dev.py`：DEV 级成对 cluster 重采样脚本，正式统计路径为 `benchmarks/evaluate.py --release`（12 项差值 + Bonferroni），词干级引用 0。
- `domimap/batch.py::scan_many()`：死函数（全仓仅定义处 1 次出现；build_many 自带并行扫描路径）。
- 未使用 import ×10：graph.py `re`、search.py `calendar`、check_release_behavior.py `subprocess`、competitor_host.py `_re`、tiny_dev/runner.py `selectors`、corpus 五脚本 `sys`/`re`（逐个 grep 实证 ≤1 次出现）。
- 本地空目录 `domimap/synth/`（未跟踪）。

## 有据保留（第一性原理审查后的结论）

- `llm_rerank.py`：实测零收益，但是默认关闭的隔离可选能力 + 11 个契约锁定负结果——负结果知识保留，代码隔离不进主路径。
- `confirm_kit.py`：M5 冻结确认（独立托管人）必备工具。
- `check_release_behavior.py`：specs/tasks/m5-final 引用。
- `setup.sh`：与 check_specs 源指纹耦合（fingerprint 文件清单），成本 20 行，删除收益为负。
- 根 `SOUL.md`：F3 可信上下文的 persona 示例（context.py RULE_FILES 的演示物），133 字节。
- `docs/archive/`：按 AGENTS 定位为历史归档，链接检查器覆盖，保留。
- `TWELVE_OF_TWELVE_RESULT.json`：有引用，保留。
- CHANGELOG 本轮未动：并行会话正在编辑该文件（安静窗口纪律）。

## 验证与回退

- 核心模块 import 冒烟；`make ci`（提交树 + 干净 venv，= GitHub CI 同款）全绿；本地 `make verify` 的证据刷新因并行会话未提交文件而暂缓（其落地时对齐指纹）。
- 回退：revert 本提交即恢复（删除项均无下游依赖）。
