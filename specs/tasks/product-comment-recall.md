# product-comment-recall：类注释关键词入检索面（有界改进第 2 轮 b）

来源：第 5 步诊断——admin-ware Dao 4 例 recall miss：查询词为类邻近中文注释关键词
（"配送 区域 限额 处理类"），而 Class 节点可检索文本只有 name/kind/file（拉丁标识符），
中文注释词与节点词面零交集，永不可召回。

## 需求/案例

- requirement：R04（查询/图检索）；acceptance：AC-R04-01（分路召回语义内的召回面扩展）。

## 变更（精确 allowlist）

- `domimap/lite_scan.py`：_scan_java 捕获类声明前的注释块（≤6 行、截 300 字符）入
  classes 记录 "comment" 字段。
- `domimap/graph.py`：Class 节点 meta 携带 comment。
- `domimap/search.py`：_node_text 对 Class 节点附加 meta.comment（仅 Class——方法级
  词面噪声风险高，本轮回滚边界明确）。
- `tests/test_comment_recall.py`：契约。

## 契约

1. 带中文注释的类可被注释关键词查询命中（file 命中）。
2. 无注释类行为不变；拉丁标识符检索不变。
3. comment 截断 300 字符（防长注释膨胀索引）。
4. 拒答语义不变（无匹配标识符仍拒答）。

## 负例

1. 注释词不得让无关类命中（同词只命中含该注释/正文的节点）。
2. 空/无注释不得产生空 comment 索引项。

## 回退

单提交回滚；三处改动各为增量行。

## 边界

- 方法级注释、注释中的业务术语→图边（如 CALLS 语义）不在本轮。
