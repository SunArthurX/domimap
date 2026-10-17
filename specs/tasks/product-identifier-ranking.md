# product-identifier-ranking：标识符精确匹配加权 + 单字噪声抑制（有界改进第 3 轮 a）

来源：干净集复评 miss 明细——cross 表召回 6 例（OP_OPERATOR/QUALIFICATION/QUA_CF_*）
与 code DDL 2 例（BATCH_JOB_EXECUTION 位置 13）。数值定位（干净批图实测）：

1. **单字 CJK token 计分污染**：查询通用尾"哪些服务 读写 跨服务"tokenize 出 哪/些/服/务
   等单字；SaleServiceDTO 仅凭 ['服务','务','服'] 以 1.29 分压过仅匹配 op_operator
   （定义性命中）的 tbl 节点（0.53 分）。单字是子词级噪声，无选择性。
2. **名称精确匹配无加权**：查询含 ≥4 字符拉丁标识符且与节点 name 完全一致（大小写不敏感）
   是定义性同一关系，应显著优先于词频堆叠。

## 需求/案例

- requirement：R04；acceptance：AC-R04-01（排序质量——召回已至、裁剪失误类）。

## 变更（精确 allowlist）

- `domimap/search.py`：
  1. `_score` 跳过单字 CJK token（len==1 且 >U+2E7F）。
  2. 候选计分后，查询拉丁单元（≥4 字符、lower）与节点 name.lower() 完全相等者
     分数 ×3（IDENTIFIER_NAME_BOOST，常量显式）。
- `tests/test_identifier_ranking.py`：契约。

## 契约

1. "X 表 哪些服务 读写"型查询：名为 X 的节点进入 top1（或前列），不再被仅凭通用
   词/单字堆叠的节点压过。
2. 无标识符的中文查询行为不回退（全量回归守护）。
3. boost 只作用于 name 完全相等（子串/前缀不 boost——不猜相近名）。

## 负例

1. 近名标识符（op_operatorr）不得因 boost 获利（不等于任何 name）。
2. 单字删除不得影响拒答语义（units 覆盖门仍按原语义）。

## 回退

单提交回滚；两处改动独立可分。

## 边界（已知限制，另立任务）

- tbl/col 节点 ID 无服务限定，双仓同名表节点合并为一（file 指向其一）——schema 迁移
  风险大，不在本轮；对 gold=双仓同名文件的题仍可命中（任一文件在 gold 集内）。
- 时效/文档查询长尾稀释（cov² 惩罚）属下一片。
