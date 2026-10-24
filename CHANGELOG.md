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

## [0.5.0] - 2026-10-21

原型演进版：检索能力与工程化显著推进，仍不声明生产可用（M5 冻结确认未执行，`make release-check` 保持关闭）。

### 检索与知识层（自 0.4.0）

- 可选 LLM 语义增强层（`domimap enrich`，2026-10-21）：可配置 anthropic 协议模型为图内 Doc 材料生成 inference 草稿笔记（`conf=LLM, prov=knowledge:llm`，claims 一律 inference/proposed，人工审定前不作事实）；幂等重跑、审计 append-only、预算/超时/并发互斥、服务端输出校验、无 key 干净退出。
- LLM 增强层生产化硬化：审计逐条落盘（中断安全、重跑零重复计费）、传输分级重试、`--budget-tokens`、同目录互斥锁、输出白名单校验与注入隔离、文档更新后旧笔记自动 supersede。
- 分路命中再融合（product-lane-fusion）：code/doc/knowledge 三路各自召回 + 融合保底落位，巨型泛词文档不再独占结果；LLM 笔记可见性 0/40 → 40/40 题。
- 可选本地嵌入语义融合（product-embedding-index）：bge-small-zh/fastembed 幂等建索引 + RRF 融合 + 融合资格门（定义性标识符/代码意图词时词法权威）——真实双集 A/B 首个净正收益：pub 23/97→36/97、dev 19/36→26/36 零回归、负例不变。
- 查询期 LLM 语义重排（product-llm-rerank）：真实 A/B 如实零效果（池外 miss 为主因），结论保留、默认关闭。
- 长文档分段（product-doc-chunking）：索引层 BM25+嵌入双端分段（3500/1500/250）——检索级全项目最大单轮收益：公开语料 50→70/140（document 6→15、freshness 6→17），全类别零回归。
- 文档意图语义召回限定 Doc/Knowledge 子池；kg_explore 工具描述与宿主提示加"原文直查优先/引用守门"（agent-loop 三臂 16→17→20/36）；题面锚词准入规则 v3（如实零改进，主因确认）；DDL 语义加权、版本号纪元提取、查询期中英桥接回退、双向路径匹配评分（索引期桥接/文档先验/双语提示经实测有害后撤销）。

### 基准与工程化（2026-10-20/21 发布整理）

- 五系统比较基础设施：四竞品原生工作流宿主 + GLM-5.3 真实主轨宿主（hermetic 契约测试）、确认套件、main_track 逐题落盘账本。同会话评测：开发集正例 24/27、公开语料 22/32，四组配对差值均为正（分表分母见 README）。
- `check_specs.py --structural` 与 `make ci`：无本地证据工件的环境可运行结构校验 + 全部测试；`make verify` 语义不变（正负契约锁定）。
- 隐私与历史：仓库与全部历史不含凭据细节、账号标识、公司名与个人路径（两轮 filter-repo，全对象扫描 0 残留）；基准脚本语料环境变量化（`DOMIMAP_DEV_CORPUS` 等，自备/开源语料指引见 benchmarks/DATA_LAYOUT.md）。
- 安全：UI 全请求回环 Host 校验（DNS rebinding 读泄露修复，R08-02 契约测试扩展）；POST 跨站写拒绝、JSON+nosniff、SQL 参数化、MCP 有界入口复核确认。
- 文档：`docs/knowledge-graph.md` 图谱模型参考、`docs/evolution.md` 成熟度差距与 E1–E6 进化计划、README 生产级 mermaid 架构图与查询数据流图、基准表分表、实测修正的快速开始。
- 社区：issue 模板（bug/feature/usage）、PR 模板、行为准则。
- 分发就绪：版本 0.5.0、`domimap --version`、PyPI Trusted Publishing 工作流（`.github/workflows/pypi.yml`，tag 与 pyproject 版本校验）；`pip install pypdf python-docx` 缺失时 PDF/DOCX 契约测试自动跳过。

## [0.4.0] - 2026-10-16

原型版本。多仓 Java 扫描（Spring/MyBatis/Dubbo/RocketMQ/通用 MQ/JPA/跨端 + lite 方法级 CALLS）、中文混合检索（诚实拒答）、领域种子打标、查询索引磁盘缓存、CLI 与 MCP stdio 服务器（5 工具）、回放验收测试（夹具级）、pyproject 打包。

已知缺陷见 docs/known-defects.md；本版本不声明生产可用，未做四竞品比较。

## [0.3.0] - 2026-10-16

定名 domimap（原占位名废弃），清除业务数据与真实仓扫描产物。

## [0.2.0] - 2026-10-16

首个可执行落地包：7 synthesizer、多仓发现/合并/增量、MCP 热重载、治理 lite、16 golden 测试。
