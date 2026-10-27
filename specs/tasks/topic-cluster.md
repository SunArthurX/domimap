# topic-cluster — RV02 剩余半项：Topic 按消息集群隔离

日期：2026-10-28。依据 out/agent-review-2026-10-27/review.md RV02（"表、列、Topic 按来源及数据源/消息集群隔离；共享关系须有明确依据"）——前一轮 entity-identity 完成方法/表/列，Topic 留待（handoff 登记遗留半项）。

## 问题：Topic 按全局名共享（`topic:<name>`），不同数据源的同名主题合并，无共享依据声明。

## 修复：`Graph._topic_cluster(prov)` 从声明 provenance 推导消息集群（rocketmq/kafka/rabbit/jms/stream；无法判定→unknown，不猜）；`_topic_declare` 建 `topic:<cluster>:<name>`——同集群同名跨服务连接为**一个**节点（共享依据=「相同声明的数据源家族+相同主题名」，即 pub/sub 按名对接的真实机制），node.meta.services 排序确定（顺序无关）+ shared_basis 说明；不同集群同名保持独立，之间无任何共享边。PUBLISHES/SUBSCRIBES 边连各自集群节点。

## 迁移兼容：Topic ID 格式 `topic:<name>`→`topic:<cluster>:<name>`，图为构建产物重建即得；旧图 JSON 可读。

## 回归（先红后绿）：tests/test_entity_identity.py::TestTopicClusterIdentity 3 项——同集群 pub/sub 连接+参与方顺序无关+依据说明；rocketmq/kafka 同名隔离且无共享边；两仓顺序反转节点/出处/边全等。golden 的 trade-price-changed 断言随格式更新。
