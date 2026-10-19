# product-en-bridge：中英技术域词汇桥（优化第 1 轮，P1-1 + P1-2 + P1-3）

来源：公共语料评测 miss 分析——8 题因中文查询无法命中英文文档（README/CHANGELOG/SPEC）。

## 需求/案例

- requirement：R04；acceptance：AC-R04-01（检索面跨语言扩展）。

## 变更（精确 allowlist）

- `domimap/tokenize.py`：EN_BRIDGE 中英同义词表（~80 组通用技术域）+ tokenize 时对 CJK token 附加英文对应词（索引期，双向可搜）。
- `domimap/search.py`：文档文件名含 README/Tutorial/Getting Started/CHANGELOG/SPEC/GUIDE 时 BM25 ×1.5（文件类型先验）。
- `domimap/seeds.json`：新增通用技术域（配置域/部署域/API 域/数据库域/消息域/安全域），每域 10-15 个中英关键词。
- `tests/test_en_bridge.py`：契约。

## 契约

1. 中文"接入 教程"能命中含 "Getting Started"/"Tutorial" 的英文 README。
2. "配置"能命中 config/configuration 相关文件。
3. README 加权只作用于文档路（代码节点不受影响）。
4. 现有中文检索行为不回退。

## 负例

- 词表不含 benchmark 特定词（如 gold 路径中的具体文件名）——只用通用技术术语。
- 不改协议/底线/评分器。

## 回退

单提交回滚。
