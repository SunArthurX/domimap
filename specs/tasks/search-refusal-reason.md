# search-refusal-reason — 拒答原因诚实化（区分覆盖率/域过滤/无强命中）

## 背景

Playwright 全流程自测（product-ui-workbench 后续轮）三次独立复现同一缺陷：
`/api/search` 拒答分支的条件是 `cov < min_cov or not scored or not strong` 三者之一，
但拒答文案一律印「查询词覆盖率 X%，不足 Y% 阈值」——当真实原因是域过滤筛空候选
（覆盖率 64% 明明达标）时，文案自相矛盾且误导排障方向（用户会去换关键词而不是检查领域值）。
这违反 R01「如实告知」与 R04 检索语义的诚实纪律。

同时：GET 型工作流输入无长度上限，超长输入撞 HTTP 414 后页面显示开发者黑话
「响应不是 JSON（HTTP 414）」，不符合工作台的诚实错误呈现。

## 范围（bounded slice）

- `domimap/search.py`：拒答 `text` 按真实原因分化（覆盖率不足 / 域过滤后无候选 /
  无强命中候选 / 无实质词强信号）；`refused` 标志与拒答判定条件不变。
- `domimap/ui.py`：检索结果拒答前缀从硬编码「拒答（覆盖率不足）：」改为「拒答：」
  （原因由后端 text 给出）；GET 型工作流（检索/两卡/影响面/证据阅读）输入超
  2000 字符时前端诚实拦截，不再发必然 414 的请求。
- 测试 `tests/test_refusal_reason.py`：原因分化断言 + 页面前缀/长度护栏断言。

**文件登记说明**（沿用 production-boundaries 的先例，见其 md 末段）：manifest `files`
除本任务 4 个文件外，还登记了同工作区并行未提交任务 product-ui-workbench 与
production-boundaries 的全部文件——仅为全 diff 范围检查（AC-R13-01）登记，
不归本片成果，不回退、不改写。

不改动：拒答判定逻辑、排序、seeds 结构、exit code 语义、MCP/CLI 输出结构。

## 契约（不可破坏）

- 拒答仍以 `refused: true` 表达（CLI exit 3 / MCP / UI 同源）；任何消费方不解析
  拒答文案（已核实：`__main__.py`/`mcp.py` 均走标志）。
- 覆盖率不足时文案保留「诚实拒答：查询词覆盖率 …阈值」语义（test_semantic_bridge
  的 REFUSE_MARK=「诚实拒答」标记保持）。
- 域过滤原因必须点名域值本身，并给出可执行下一步（领域地图可查可用域）。
- 页面纯 DOM API 纪律不变（不出现 innerHTML 字样）；长度护栏消息用中文人话。

## 负例

- 覆盖率真不足的查询（全生僻词）：仍得到覆盖率文案（不能因本次改动丢失原因）。
- 无域过滤时无强命中：文案不得提域过滤。
- 前端拦截不改变合法短输入行为；note（POST）不加 URL 长度护栏。

## 验证

- `python3 -B -m unittest tests.test_refusal_reason tests.test_negative_refusal tests.test_semantic_bridge tests.test_ui_workbench -v`
- `make verify`
- Playwright 重跑检索工作流成功/域过滤/生僻词三态 + 50 轮浸泡（见
  out/verification/ui-workbench-soak-50.json 当前指纹重跑记录）。

## 验证现状（2026-10-24，定稿）

- 单测：4 个新测试过；refusal/negative/semantic-bridge/ui-workbench 组合 35 测试过
  （含并行 production-boundaries 改写 /api/read 接 read_evidence 之后的合并态）。
- 浏览器三态实测过：域过滤拒答点名「order」不再自相矛盾；生僻词保留覆盖率文案；
  >2000 字符前端诚实拦截。50 轮浸泡 50/50 过（详见
  out/verification/ui-workbench-soak-50.json `rerun_2026-10-24_b_after_refusal_fix`）。
- 证据定稿：两遍 refresh（fp 7e00e04d 起），manifest 登记说明见上；make verify 终态
  见交接 out/handoff.md。

## 回滚

revert `domimap/search.py`、`domimap/ui.py` 两个文件本任务差异 + 删除
`tests/test_refusal_reason.py`；无数据迁移。
