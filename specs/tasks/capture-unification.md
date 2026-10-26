# capture-unification — D10：扫描即固化，普通 build 走证据契约

日期：2026-10-26。依据 docs/superpowers/plans/2026-10-26-drift-analysis-and-priorities.md Task 4；关闭 docs/known-defects.md D10。

## 关联需求与案例

- R02（版本化证据：外部返回的 ID 发布前有可读不可变片段）、R03（构建一致性：更新恢复不误报）。
- AC-R02-01（首次 build 即返回可引用 ID——此前普通单仓 build 发布零证据图）；AC-R02-02（覆盖缺口可见——捕获失败不再被吞）；AC-R03-02（手动更新不误报/不报"无 manifest"——普通 build 产物现可 update）。

## 问题

`domimap/__main__.py:101-105` 单仓/`--merge` 路径调 `graph.build()`，从不构造 EvidenceStore，只有 `--discover` 走 `batch._publish`；且 `_publish` 对每个文件再读一次磁盘（`lite_scan.py:103-108` 文本读 vs `store.py:57-58` 二进制读），两读之间源被改写即产生"图来自版本 A、证据来自版本 B"；捕获 OSError/ValueError 被 `continue` 吞掉（`batch.py:76-78`）。

## 预期用户结果

- `domimap build <repo> -o out`：out/<name>/ 下有 graph.json、coverage.json、store.db、gens/、blobs/、<label>/manifest.json；`kg_explore` 尾部的 ev_id 可经 `kg_read` 读取；`domimap update -o out/<name>` 可用（无变更 no-op，有变更重建），不再 exit 5。
- 一次构建中每个源文件只从磁盘读一次：`scan_repo(root, repo_label, capture)` 读 raw 字节 → 回调固化（`capture_source(..., raw=raw)` 不再开文件）→ 同一份字节解码解析（`_decode_text`：utf-8 严格→gb18030 宽容，统一换行，与文本模式等价）；docx/pdf 经 `io.BytesIO(raw)` 抽取（同源）。
- 捕获失败进 `coverage.skipped`（reason 以"证据捕获失败："开头）；读取失败亦登记。
- 服务命名策略进 manifest（`service_prefix`）：单仓 build 为 None（不加仓名前缀，节点 ID 与既往一致）、多仓发现为仓名；`update` 沿用记录，节点 ID 不漂移；旧 manifest 缺该键按仓名前缀处理（既有行为）。

## 契约

- `lite_scan.scan_repo(root, repo_label=None, capture=None)`；`lite_scan.extract_document(path, raw=None)`。
- `EvidenceStore.capture_source(repo, sid, abs_path, rel, raw=None)`。
- `batch.build_many(roots, out_dir, jobs=8, force=False, merged_name=None, labels=None)`；`batch.publish_generation(store, g, out_dir)`；`batch.update` 读 `service_prefix`。
- `graph.build(repo_root, out_dir, seeds_path=None)` → 委托 `build_many([root], out_dir, force=True, labels={root: None})`。

## 设计选择

- 一条发布路径：删除 `_publish` 的二次遍历捕获，所有入口经 `build_many`；而非在 graph.build 再写一套 store 逻辑。
- 捕获覆盖全部遍历文件（含未解析扩展名）——保持既有证据范围；因此非解析文件也读一次（总读盘次数由"解析文件 2 次 + 其他 1 次"降为"全部 1 次"）。
- 命名策略记录而非推断（len(roots)>1 推断会改变 discover 单子仓的既有 ID）。

## Given/When/Then

- 正例：build 后真实来源文件节点全部有 ev_map 条目且 read_evidence available；builtins.open 计数每个夹具文件 ≤1；update 无变更 no-op、改源后 rebuild 且非 doc 节点集合不变、无 `svc:mini:` 前缀；discover 模式 manifest.service_prefix=仓名。
- 负例：注入 capture_source 抛 ValueError → coverage.skipped 含该文件与"证据捕获失败"。

## 验证 / 回滚

见 manifest。617 tests OK（含 6 项新测试）。

## 遗留

- manifest 文件签名仍为 (mtime_ns,size)（T6 改内容哈希）；graph.json/coverage/manifest 原子发布（T6）；来源身份 basename（T5）。
