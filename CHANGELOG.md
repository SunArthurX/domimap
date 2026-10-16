# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式与语义化版本。

## [Unreleased]

### 计划中（按 docs/roadmap.md M0–M5 交付，未完成不得在此列为已完成）

- M0 工程基线：Git、CI、安装闭环、四竞品比较协议 spike。
- M1 可信身份/来源/固化证据/generation 发布与恢复。
- M2 公共检索服务、CLI/MCP/只读 UI、四客户端首条真实链路、时间策略。
- M3 人工知识事务闭环（保存/修订/审定/复核/恢复）。
- M4 四客户端完整联调、格式/平台矩阵、并发与安全加固。
- M5 冻结确认比较（对四竞品三指标严格胜出）、生产验收与发布。

## [0.4.0] - 2026-10-16

原型版本。多仓 Java 扫描（Spring/MyBatis/Dubbo/RocketMQ/通用 MQ/JPA/跨端 + lite 方法级 CALLS）、中文混合检索（诚实拒答）、领域种子打标、查询索引磁盘缓存、CLI 与 MCP stdio 服务器（5 工具）、回放验收测试（夹具级）、pyproject 打包。

已知缺陷见 docs/known-defects.md；本版本不声明生产可用，未做四竞品比较。

## [0.3.0] - 2026-10-16

定名 domimap（原占位名废弃），清除业务数据与真实仓扫描产物。

## [0.2.0] - 2026-10-16

首个可执行落地包：7 synthesizer、多仓发现/合并/增量、MCP 热重载、治理 lite、16 golden 测试。
