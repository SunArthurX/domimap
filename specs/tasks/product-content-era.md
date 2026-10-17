# product-content-era：文档内容纪元优先（first_seen 来源治理，第 6 轮）

来源：第 5 轮节点级追踪的审计结论——Doc 节点 first_seen=文件 mtime（graph.py），
Class/Method/SqlStmt/Table 等代码节点无时间元数据（None，按"未知=最早"语义处理）。

## 为什么必要（确认侧硬前置）

确认候选语料为 27 个公共仓 **depth-1 克隆——git clone 将全部文件 mtime 置为克隆时刻**。
届时所有文档的文件时间=今天：时效题的近因排序将完全失真（新旧不可分）。
文档内自述日期（修订历史/发布日期/copyright 年份）是唯一可靠纪元。

## 需求/案例

- requirement：F4（时间策略）；acceptance：AC-F4-01（时间资格与排序的时间事实来源治理）。

## 变更（精确 allowlist）

- `domimap/lite_scan.py`：文档记录提取 `content_era`（正文最新日期 → epoch 秒；
  复用与生成器一致的日期正则）；带 `era_source` 标注（content/mtime）。
- `domimap/graph.py`：Doc 节点 `first_seen = content_era or mtime`，meta 携带 era_source。
- `tests/test_content_era.py`：契约。

## 契约

1. 文档含正文日期 + 新 mtime（克隆形态）→ first_seen=内容纪元（非 mtime）。
2. 无日期文档 → mtime 兜底，era_source=mtime。
3. front-matter valid_until/superseded_by 语义不变。
4. 代码节点不新增时间（"未知=最早"语义已由第 5 轮重加权落实）。

## 负例

- 不可从文件名/目录猜测纪元（只认正文日期）。
- 触碰文件（mtime 变新）不改变内容纪元。

## 回退

单提交回滚；两处改动。

## 边界

- 只取文档正文日期；代码文件内的注释日期不入纪元（防噪声）。
