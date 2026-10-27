# entity-identity — RV02：重载/跨仓同名实体身份（先红后绿）

依据 out/agent-review-2026-10-27/review.md RV02。

## 问题：`find(String)` 与 `find(Integer)` 参数数量相同而合并（mth ID 只含 argc）；两仓同名 DDL 表合并为一个 tbl 节点且出处随构建顺序变化。

## 修复：方法 ID 含完整参数类型签名 `mth:<svc>:<cls>.<name>(<types>)`（跨行签名未知记 `?` 且 meta.sig_unknown=True，不猜）；表/列按**声明方服务**隔离 `tbl:<svc>:<name>`/`col:<svc>:<t>.<c>`（DDL 与 JPA 实体都是声明）；mapper 按名引用只在**已声明**表中找候选——单候选显式连接、多候选逐条 AMBIGUOUS（不合并）、零候选在本服务作用域建 `unresolved` 节点且**不**入名字索引（其他服务不得连接推断节点，否则首个被扫描方决定归属）；Topic 保持全局名（主题名即消息集群）但处理排序使出处与构建顺序无关；调用/HANDLES/CALLS_SQL/PUBLISHES 均经 `_mth_candidates` 按签名节点解析。

## 迁移兼容：ID 格式变化（`#argc` → `(sig)`、`tbl:` 限定）——图为构建产物可全量重建；冻结回放样本跨代码指纹本就不可比；旧图 JSON 可读（ID 只是字符串）。

## 回归：tests/test_entity_identity.py 6 项（重载分离、跨仓方法、DDL 隔离+顺序反转 ID/出处/边全等、mapper 单/多候选、签名格式）；既有 6 个测试文件的 ID 断言随格式更新（golden/precision/m2_f4/m4_matrix/p1）。
