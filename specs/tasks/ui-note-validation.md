# ui-note-validation — note/save 服务端参数校验 + 运行面板 Enter 提交与画布竞态守卫

## 背景

第三轮"每次全新加载重测"前置探测（2026-10-25）发现：

1. **`POST /api/note/save` 不校验 body**（真缺陷，两次复现）：缺 `body` 字段或纯空白
   正文均返回 200 并创建空笔记（`body.get("body", "")` 兜底空串直接入库）——UI 前端
   挡住了空正文，但任何直接调 API 的客户端都会制造垃圾笔记进入检索池，违反
   "空参/非法参 4xx JSON，不静默"契约（product-ui-workbench 明文）。
2. **输入框 Enter 键不触发运行**（UX 缺陷）：运行面板无 `<form>`，Enter 无任何反应；
   工程控制台惯例是 Enter 运行（textarea 保留 Shift+Enter 换行；中文输入法组词态
   的 Enter 不得触发——需 `isComposing` 守卫）。
3. **运行中切换工作流的画布状态污染**（理论竞态，防御性加固）：本地实测响应
   22ms 内完成、窗口不可达；但慢盘/远程隧道下，旧 run 的 `finishRun` 会把新工作流
   画布的全部节点标成 done/fail（`CURDIVS` 为模块级、被新画布重置）。一行
   `CUR!==wf` 守卫消除。

对照：并发幂等语义正确（同 key 同文去重、异文同 key 409 幂等键内容不一致）、
坏 JSON 400 正确——不在本片范围。

## 范围（bounded slice）

- `domimap/ui.py`：
  - `/api/note/save`：`body` 缺失/非字符串/`strip()` 后为空 → 400 `{"error":"正文不能为空"}`；
    `claims` 非 list → 400；`idempotency_key` 保持可选（与 CLI 语义一致）。
  - 运行面板输入控件 Enter（非 composing、textarea 非 Shift+Enter）→ 触发运行。
  - `finishRun(wf,ok)` 首行 `if(CUR!==wf) return;`。
- 测试 `tests/test_ui_note_validation.py`：API 四态（缺 body/空白 body/claims 非 list/
  合法 200 不回归）+ 页面字符串断言（isComposing 守卫、finishRun 守卫在位）。

## 契约（不可破坏）

- 合法保存行为、幂等键冲突 409、保存后即时可检索、`refreshStats` 不变。
- 页面纯 DOM API（无 innerHTML 字样）、CSP、回环校验不变。
- Enter 行为不得影响 textarea 多行输入（Shift+Enter）与 IME 组词确认。

## 负例

- `{"claims":[]}`（原缺陷用例）→ 400，且不创建笔记（计数不变）。
- `{"body":"  ","idempotency_key":"k"}` → 400。
- 合法保存两连发同 key 同文 → 仍幂等去重（200 同 note_id）。

## 验证

- `python3 -B -m unittest tests.test_ui_note_validation tests.test_ui_stats_fresh tests.test_ui_workbench tests.test_refusal_reason -v`
- `make verify`
- 第三轮 50 次全新加载重测（含新用例：API 空 body 400、Enter 触发、切换后画布零污染）。

## 验证现状（2026-10-25，定稿）

- 单测：5 个新测试过（缺 body 400 且计数不变、空白 body 400、claims 非 list 400、
  合法保存+幂等重放不回归、页面守卫断言）；组合 26 测试过。
- 第三轮全新加载重测 50/50 全过（out/verification/ui-retest-50/results-c3.json）：
  前 40 轮带证据库（33 用例/轮），第 41–50 轮切无证据库索引（31 用例/轮，自适应
  预期）——无固化证据时候选无 ev、证据阅读如实不可用、其余流程全部正常；5 个服务
  周期日志均 0 行；控制台 161 条全为预期 4xx。
- 证据两遍定稿 + make verify 终态见 out/handoff.md。

## 回滚

revert `domimap/ui.py` 本任务差异 + 删除 `tests/test_ui_note_validation.py`；无数据迁移。
