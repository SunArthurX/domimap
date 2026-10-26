# ui-stats-fresh-load — 页眉统计随每次页面加载刷新（不再冻结启动快照）

## 背景

「每次全新加载重测」（ui-retest-50）第 2–4 轮复现：长驻 `domimap ui` 服务里保存笔记后，
新打开/刷新的页面页眉**不显示笔记数**（`STATS.notes=null` 是服务启动时刻的快照——
`make_server` 在启动时一次性 `render_page` 并把整页 HTML 冻进闭包，`/` 处理器永远返回它）。
单页长驻的使用路径（保存后 refreshStats）掩盖了该缺陷；工作台是长驻服务，
build/embed/note 等状态变化后刷新页面看到的是过期统计，违反"如实呈现"（R01）。

## 范围（bounded slice）

- `domimap/ui.py`：`/` 处理器改为每请求 `render_page(graph_path, g)`（图规模来自已加载
  Graph 对象；knowledge/store/embed 状态每请求实时探测）。删除启动时的 `page` 冻结变量。
- 测试 `tests/test_ui_stats_fresh.py`：保存笔记前后各 GET `/`，
  断言新加载页面的注入 STATS 笔记数即时可见（无需任何客户端刷新）。

## 契约（不可破坏）

- 页面纯 DOM API、CSP 头、回环校验全部不变（仅改 stats 的取数时机）。
- `/api/stats` 语义不变（本来就是实时的）。
- `_page_stats` 每请求打开 knowledge.db 仅为计数（本地单用户 UI，开销 ~1ms，可接受）。

## 负例

- knowledge.db 不存在时页面仍显示无笔记（不报错、不显示 null 转义的异常文案）。
- 保存失败时页面统计不得虚增。

## 验证

- `python3 -B -m unittest tests.test_ui_stats_fresh tests.test_ui_workbench tests.test_refusal_reason -v`
- `make verify`
- Playwright 全新加载重测（ui-retest-50 后续轮次）确认 note-save 页眉断言通过。

## 验证现状（2026-10-24，定稿）

- 单测：2 个新测试过（保存后全新加载注入 STATS 即含新笔记数；无 knowledge.db 页面正常）；
  组合 21 测试过。
- 全新加载重测 50 轮（out/verification/ui-retest-50/results.json）：第 2–4 轮如实捕捉本缺陷；
  修复后第 5–50 轮连续 46 轮全过（含同一断言与 5 个冷启动周期）。
- 证据两遍定稿 + make verify 终态见 out/handoff.md。

**文件登记说明**（同 search-refusal-reason 的先例）：manifest `files` 除本任务 3 个文件外，
登记同工作区并行未提交任务（product-ui-workbench / production-boundaries /
search-refusal-reason）的全部文件——仅为全 diff 范围检查（AC-R13-01）登记，不归本片成果。

## 回滚

revert `domimap/ui.py` 本任务差异 + 删除 `tests/test_ui_stats_fresh.py`；无数据迁移。
