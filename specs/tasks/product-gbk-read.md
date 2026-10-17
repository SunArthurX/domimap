# product-gbk-read：源码读取 GB18030 回退（有界改进第 3 轮 b）

来源：干净集复评——注释桥 4 例（AreaLimitTaskDao 等）仍 recall miss；实况核查：
admin-ware Dao 文件为 **GBK 编码**，lite_scan 以 utf-8 errors=replace 读入后中文注释全部
乱码，第 2 轮 b 的注释桥对 GBK 文件失效。（v2 生成器早前已因同一真相修复过文档侧。）

## 需求/案例

- requirement：R04（检索面完整性——GBK 注释是目标工作负载的实况）；acceptance：AC-R04-01。

## 变更（精确 allowlist）

- `domimap/lite_scan.py`：scan_repo 的文件读取改为 utf-8 严格失败 → GB18030（errors=replace）
  回退（与 benchmarks/corpus/generate_questions_v2.read_text 同一模式）。
- `tests/test_gbk_read.py`：契约。

## 契约

1. GBK 编码 Java 文件的中文注释进入节点可检索文本（查询命中）。
2. utf-8 文件行为不变；混合/损坏字节不崩溃（最终 replace 兜底）。

## 负例

- 非 GBK 二进制垃圾不得产生伪中文 token（严格→回退→replace 的链路保证）。

## 回退

单提交回滚；单点改动。

## 边界

- docx/pdf 走独立抽取器不受影响；html 的 GBK meta charset 侦测不在本轮（如实记录）。
