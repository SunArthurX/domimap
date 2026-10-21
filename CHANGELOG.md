# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式与语义化版本。

## [Unreleased]

### 已落地（原型推进；均为同会话开发者评测，不构成发布验收，`make release-check` 仍关闭）

- 五系统比较基础设施：四竞品适配器与原生工作流宿主（Codebase-Memory-MCP 走动态发现的 MCP 工具；CodeGraph / Graphify / claude-obsidian 走各自原生 CLI），GLM-5.3 真实主轨宿主（hermetic 契约测试，无网络无费用），独立托管人用确认套件 `benchmarks/confirm_kit.py`。
- 同会话评测结果：开发集 33 题 domimap 正例 24/27，公开语料（27 个未暴露开源族）40 题 22/32；对四竞品的配对差值均为正，但公开语料上差距明显收窄。分表与分母见 README。
- 检索优化：DDL 语义加权（Table 节点）、版本号纪元提取、查询期中英桥接回退；索引期桥接、README 文档先验与双语提示引导三项在公开语料上被证实有害后撤销。
- 工程卫生（2026-10-20）：`scripts/check_specs.py --structural` 与 `make ci` 供无本地证据工件的环境（CI / 新克隆）使用，`make verify` 的证据校验语义不变并有正负契约测试锁定；主轨宿主的凭据加载改为环境变量 / 本机未入库 helper，仓库内不再含凭据库解密细节与账号标识；CI 显式安装 PDF/DOCX 可选解析器，相关契约测试在缺依赖时跳过而非报错。
- LLM 增强层生产化硬化（product-llm-enrich-hardening）：审计改 append-only `enrichment.jsonl` 逐条落盘（中断安全、重跑零重复计费，兼容旧 v1 只读）；传输分级——4xx 不重试、429/5xx 尊重 Retry-After 指数退避抖动、`--timeout`；`--budget-tokens` 预算中止；同目录 `.enrich.lock` 并发互斥；输出服务端校验（evidence_paths 白名单剔编造、长度上限截断、未知字段记录、双语 keywords 警告）与材料分隔符注入隔离；文档更新后旧 LLM 笔记自动 supersede 撤回（`--keep-old`）；`--targets docs|domain|all`；serve 热重载感知 knowledge.db；doctor 增 LLM 段；`--json` 逐篇明细与成本估算。契约 15→31；真实 GLM-5.3 A/B 收益评测见 task 记录。
- 可选 LLM 语义增强层（product-llm-enrich，2026-10-21）：`domimap enrich` 一条命令把图内 Doc 材料交给可配置的 anthropic 协议模型（默认 glm-5.3）生成 inference 草稿笔记——`conf=LLM, prov=knowledge:llm`，claims 一律 `inference/proposed`，人工审定前不作为事实（AC-R05-02 纪律）；幂等重跑（同图同模型零调用零新笔记）、`--dry-run`/`--force`、审计文件、无 key 干净退出（码 6）；`query`/MCP `kg_explore`/UI 统一挂接图旁 `knowledge.db`（人工笔记 conf=HUMAN 语义不变）；14 个 hermetic 契约测试，构建期零模型调用的离线路径不变。
- 发布前二次整理（2026-10-20）：新增 `docs/knowledge-graph.md` 图谱模型参考（节点/边类型、置信度与来源语义、证据层、时间模型、检索数据流，面向人与 AI Agent）；基准脚本语料全面脱敏——语料根/外部文档族/文档优先族/预建图改为 `DOMIMAP_DEV_CORPUS`、`DOMIMAP_EXTRA_FAMILIES`、`DOMIMAP_DOC_FAMILIES`、`DOMIMAP_DEV_GRAPH` 环境变量（未设置时入口明确报错），文档与测试夹具中不再出现公司名或内部语料名；`benchmarks/DATA_LAYOUT.md` 增自备语料指引（企业私有或 ≥20 个不相关开源族均可）；社区配套（issue 模板、PR 模板、行为准则）；README 补 `kg_troubleshoot` 工具。

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
