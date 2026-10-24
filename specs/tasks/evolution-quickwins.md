# evolution-quickwins：成熟度评估后的首轮产品化改进（安全修复、分发就绪、进化计划、mermaid 文档）

- 关联：R08（安全加固，AC-R08-02：UI 请求边界）；R13（可执行防偏离约束，AC-R13-01）。
- 来源：用户 2026-10-21 目标——先判定是否成熟产品（结论：否，判定依据见 docs/evolution.md §0/§1），
  走改进分支：安全扫描与修复、生产级 README 原理图、分发就绪、详尽进化计划。
- 边界：不改检索语义与建图行为（检索层的嵌入/分段等由并行任务完成，本任务只做文档吸收与工程化）。

## 正例 / 负例

- 正例：非回环 Host 的 GET/POST 一律 403（DNS rebinding 读泄露修复），回环 Host 正常服务；既有跨站写拒绝契约不回退。
- 正例：`domimap --version` 输出版本；pyproject 与 `__init__` 版本一致（0.5.0）；pypi 工作流 tag 与 pyproject 版本不一致即失败。
- 正例：README mermaid 架构图与查询数据流图反映当前真实形态（含可选嵌入泳道、文档分段、可选 enrich 层），文档链接全部可达。
- 负例：仓库与历史不得出现公司名/个人路径/凭据（终扫 0，延续 publish-openprep* 纪律）。

## 实施

1. `domimap/ui.py`：`do_GET` 增加回环 Host/来源校验（原先仅 POST 校验，GET 可被 DNS rebinding 读取索引内容）；模块 docstring 修正"只读"表述（含回环内笔记写入口）。`tests/test_m4_security.py` 增 DNS rebinding 契约（外域 Host GET 403 ×2 + 回环 Host 200）。
2. 安全面复核结论（未改动项，记录于本 spec）：回环绑定强制、POST Origin/Referer 校验、JSON+nosniff+textContent（无 XSS）、SQL 全参数化、MCP 工具入口有界（R08-03）、证据 ID 正则校验、无 eval/pickle/shell；已知限制（接受）：docx/pdf 解压在库内、扫描超大文件无上限——威胁模型为"用户扫描自有仓库"。
3. 分发就绪：版本 0.5.0（pyproject + `__init__`）；`domimap --version`；`.github/workflows/pypi.yml`（release tag → build → Trusted Publishing，environment pypi，tag 与 pyproject 版本校验）；CHANGELOG 折出 0.5.0（吸收并行任务条目：enrich/硬化/三路融合/嵌入融合/重排零效果/分段/查询纪律/题质 v3）。
4. 文档：`docs/evolution.md`（差距矩阵 vs 四竞品 + E1–E6 里程碑，E3 按并行进展更新为"主体已落地"）；README ASCII 架构图替换为 mermaid×2（架构 + 查询数据流，含可选语义泳道与 enrich 层）；docs/README.md 与 README 文档表挂接 evolution.md；knowledge-graph.md 补分段条目（rerank/嵌入由并行任务已写入）。

## 验证与回退

- `python3 -B -m unittest tests.test_m4_security`；`python3 -m domimap --version`；refresh_evidence 后 `make verify` 全绿；新克隆 `make ci`。
- 回退：revert 本提交（UI 校验回退会重开 DNS rebinding 读口，不建议）。
