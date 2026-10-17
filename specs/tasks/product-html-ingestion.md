# product-html-ingestion：HTML 文档摄入（第 5 步诊断驱动的有界改进 第 1 轮）

来源：开发集诊断（out/diagnostic-runs/pilot-score-v1.json）——**7 个 ingestion miss 全部是 .html**
（GitLab wiki 页、javadoc apidocs、门户 sy_html、help-doc）：lite_scan 的 DOC_EXT={.md,.txt}，
.html/.htm 不在摄入范围，证据永不可能被检索到。

## 需求/案例

- requirement：R09（格式支持）；acceptance：AC-R09-01（格式状态区分语义延续：
  可解析→摄入；无文本层→显式 skipped，不静默）。

## 变更（精确 allowlist）

- `domimap/lite_scan.py`：`.html/.htm` 纳入扫描；stdlib 去标签抽取
  （script/style/head 剔除、数值/常见命名实体解码、空白规整）；空文本层显式记
  coverage.skipped。无新依赖。
- `tests/test_html_ingestion.py`：契约测试。

## 契约

1. 含正文 html → R["docs"] 含去标签文本；`<script>/<style>` 内容不进入。
2. 数值实体（&#20013;）解码为中文；常见命名实体（&amp; 等）解码。
3. 仅标签无文本 → coverage.skipped 记"HTML 无文本层"（五态语义：不冒充成功）。
4. Graph/Searcher 集成：html 文档可被查询命中。
5. 现有 .md/.txt/.docx/.pdf 行为不变（全量回归）。

## 负例

1. script 内的中文词不得通过检索命中（防脚本代码当正文）。
2. 空 html 不得产生空文本 doc 节点。

## 收益验证（dev）

同一 40 题重跑 domimap（重建图）→ dev_score 复评：.html 类 ingestion miss 应消除
（转为命中/召回/排序）；其余类别不回退。

## 回退

单提交回滚；lite_scan 改动集中于一个分支。

## 边界

- GBK 编码 html（meta charset）不在本轮（utf-8 replace 读入，乱码文本自然空→skipped，
  如实记录）；实体解码仅数值+五个常见命名实体，不引依赖。

## 收益验证结果（2026-10-17 复评，diag-0fee324e0a2e，out/diagnostic-runs/pilot-score-v2-html.json）

- **ingestion miss 7 → 0**（目标达成：.html 证据全部入图，含 javadoc/GitLab wiki/门户页/帮助页）。
- Hit@5 持平 16/32（必要非充分）：miss 归因后移 recall 7→15、ranking 3→2——瓶颈从"摄入"转为"召回/排序"。
- **连带发现（gold 质量维度）**：部分"recall miss"实为题/gold 质量问题——sy_html 等 mock 页占位文本（"谁谁谁/啥啥啥"）被 v2 生成器当主题词，短查询实测亦无法命中（文档正文无实质主题词）。下一轮需：①注释关键词→代码文件的召回（admin-ware Dao 4 例）；②生成器 gold 质量过滤（mock 页启发式）；③负例 seeds.json 噪声与 ranking（位置 13/13/24）。
- 契约测试 5/5 绿；全量回归随后执行。
