# graph-scan-precision — 扫描正确性与跨仓骨架

日期：2026-10-28。依据评审计划 T1–T7、T11（解析缓存）、T14–T15、T17 的可执行切片。

## 问题

方法体按声明后 3000 字符截取，后面的方法调用被算进前面的方法；同类裸调用按全仓简单类名匹配。Spring 类级 `@RequestMapping(value=..., produces=...)` 丢掉前缀。Dubbo 提供方只按类名等于接口名匹配，实现类连不上。没有 Maven 模块边、DDL 注释、enum/第二类、定时任务，也没有工作区级注解规则。增量更新时未变更仓仍全量重扫。

## 预期

- 方法体按花括号配对；裸调用只在本文件同类里解析；字段类型按文件隔离。
- 类级路由前缀保留额外属性。
- `@DubboService` 的 `implements` 接口连接消费方。
- `rules.json` 的 `provider_annotations` / `consumer_annotations` 走同一条 RPC 路径（公开仓库不写厂商专有注解）。
- 同一次合并图里，pom 的 artifactId 依赖连成 `DEPENDS_ON`。
- DDL `COMMENT` 进入表/列并可检索。
- enum 与同文件第二个类都建节点；`@Scheduled` 建 Job，`TRIGGERS` 指向方法。
- `records.json` 与 manifest 签名一致时，update 不重扫该仓。
- `<workspace>/domimap.seeds.json` 覆盖域并合并 `_synonyms`。
- `domimap map` / `trace` 读服务关系与正向因果链。

## 负例

- lambda / 匿名类里的调用不归属外层（既有精度夹具）。
- 规则文件缺失时行为与只有内置 Dubbo/RocketMQ 时一致。
- 缓存签名不一致则重扫，不把旧解析结果当成新源码。

## 回滚

还原本切片文件并重建图。节点新增 Module/Job，边新增 DEPENDS_ON/TRIGGERS；旧图不读这些也仍可查询。
