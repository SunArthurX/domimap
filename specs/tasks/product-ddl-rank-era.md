# product-ddl-rank-era：DDL 加权 + 版本纪元 + 输出信息标注（优化第 2-4 轮合并）

来源：公共语料 miss 分析——DDL 文件被 Java 注释压出（2 题）、版本号日期不识别（4 题）、Agent 引用选错文件（3+ 题）。

## 需求/案例

- requirement：R04（检索）、F4（时间策略）；acceptance：AC-R04-01、AC-F4-01。

## 变更（精确 allowlist）

### 第 2 轮：DDL 语义加权

- `domimap/search.py`：
  - `_score` 中 SqlStmt 节点含 `CREATE TABLE` 且查询含"表|定义|写入|位置|DDL"时 ×2 boost。
  - `kg_explore` 渲染时 SqlStmt 行标注 `[DDL]`。

### 第 3 轮：版本号纪元

- `domimap/lite_scan.py`（`_content_era`）：
  - 提取 `v\d+\.\d+` / `Release \d+\.\d+` / `\d{4}\.\d+` 形态（换算为 epoch 近似值）。
  - 正文日期 > 版本号日期（优先级）。

### 第 4 轮：kg_explore 输出信息增强

- `domimap/search.py`（`_render`）：
  - Doc 行追加 `[rank:#N]`（按 BM25 分数在当前结果中的排名）。
  - Doc 行追加 `[type:README|SPEC|CHANGELOG|TUTORIAL|GUIDE|MIGRATION|DOC]`（按文件名推断，仅提供信息不加权）。
- **不加权**（第 1 轮教训：文件类型先验加成有害——宽泛内容压特定文件）。信息标注只影响 Agent 的引用选择，不影响检索排序。

- `tests/test_ddl_rank_era.py`：契约。

## 契约

1. "xxx 表 定义 写入 位置"查询中 DDL SQL 文件应排在 Java 引用前。
2. 含 `Release 2.4` 的 CHANGELOG 的 content_era > 无日期文件。
3. kg_explore 输出含 rank 和 type 标注。
4. 现有检索行为不回退（全量回归）。

## 负例

- 版本号提取不得把 `v1.0` 中的 `1.0` 当日期（需 v/Release 前缀或 4 位年份）。
- type 标注不影响排序（不加权——第 1 轮教训）。

## 回退

单提交回滚。
