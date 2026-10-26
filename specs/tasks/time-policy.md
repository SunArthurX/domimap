# time-policy — F4：资格先于排序、as_of 三入口可达、时效可解释、复制/touch 不刷新

日期：2026-10-26。依据 docs/superpowers/plans/2026-10-26-drift-analysis-and-priorities.md Task 9。

## 关联需求与案例

- F4 时间策略；product#7 "Source families, validity, support and conflicts precede temporal ranking. Copying, touching… does not renew verification."
- AC-F4-01（冻结 as_of 与旧/未知/未来/有效/替代资料 → 历史范围正确；touch/复制不刷新；衰减可解释）。

## 问题（漂移审计 §2.3/§3 F4 行）

`search.py` 的 superseded_by/valid_until 资格门槛只在 `if as_of is not None:` 分支内（默认查询放行过期/被替代资料，与注释"默认排除"相悖）；`as_of` 在 CLI/MCP/UI 零出现；`time_note` 计算后从不渲染；图平面 `first_seen = content_era or mtime`（touch/复制制造新鲜度）；`_content_era` 把 front-matter 的 `valid_until` 日期当正文纪元。

## 预期用户结果

- 资格：`clock = as_of or now`；`superseded_by` 一律不具资格；`valid_until < clock` 不具资格（日期非法保持资格）；`as_of` 下 `first_seen > as_of` 不参与。
- 入口：`service.parse_as_of`（None/""→None；epoch 秒 2000–2100；`YYYY-MM-DD` UTC 零点；否则 `ServiceError(invalid_params)`）；CLI `query --as-of`（非法 exit 2）；MCP `kg_explore.as_of` integer schema；UI `/api/search?as_of=&top_k=`（非法 400）。
- 解释：`_render` 附 `[time:<note> era=<content|store|mtime>]`、`[valid_until:…]`；UI 种子 `time_note/era_source/valid_until`。
- 纪元：`capture_source` 返回 `first_seen`（content_first_seen 按 sha 取 min）→ `_capture_into` 记录 → `_stamp_sid` 给无正文日期的 docs 戳 `content_first_seen` → graph `first_seen = content_era or content_first_seen or mtime`，`era_source` 相应为 content/store/mtime。
- `_content_era(body)` 只看去 front-matter 的正文。

## Given/When/Then

- 正例：默认查询不含过期/被替代文档且含现行文档；as_of=2019-06 时 2020-01 到期文档具资格、2026 现行文档不参与；三入口 as_of 同结果且文本含 `[time:`、UI 含 time_note/valid_until；无日期文档 era_source=store，touch 后重建 first_seen 不变，复制件 first_seen 等于原件。
- 负例：`parse_as_of` 对 "not-a-date"/99/"2200-13-99"/True 抛 ServiceError；CLI `--as-of someday` 非零退出且提示含 as_of；MCP 传字符串 as_of 被 schema 拒绝。

## 设计选择

- 过期资料默认排除而非降权：规范要求资格先于排序；历史范围由 as_of 提供，不以"展示但降权"模糊资格。
- 纪元链 content > store > mtime：正文自述日期最可信；内容首次收录是稳定的、复制不变的次优事实；mtime 仅旧记录兼容。

## 验证 / 回滚

见 manifest。646 tests OK（含 5 项新测试；两处契约测试随可选字段/参数更新）。

## 遗留

- AC-F4-02 版本复核（陈旧标记接线）→ T11；coverage 门在小语料 + seeds 扩展下对短查询偏严（R15 检索质量范畴）。
