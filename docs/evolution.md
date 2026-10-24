# domimap 进化计划（Evolution Plan）

本文回答一个问题：**从"能力已验证的原型"到"成熟的开源产品"，还差什么、按什么顺序补、每步怎么算完成。** 与 [roadmap.md](roadmap.md) 的关系：roadmap 管 M0–M5 的产品验收闭环（不变），本文管产品化/生态维度（M5 之外或并行）。差距结论基于与四个同类系统（Codebase-Memory-MCP / CodeGraph / Graphify / claude-obsidian）的实测对比（见 README 基准表）与本仓库自身的治理状态（`make release-check` 仍关闭）。

## 0. 现状定位（诚实版）

**能力**：在"中文企业 Java 多仓 + 证据引用"利基内，同宿主同预算对比四竞品，两套语料答案层配对差值全部为正（开发集 24/27 vs 9/27 以下；公开语料 22/32 vs 17/32 以下），负例拒答 4/4。检索层在 2026-10-21 的嵌入融合 + 文档分段后达到公开语料路径级 70/140（doc 15/30、fresh 17/30，全类别零回归）。**产品成熟度**：v0.5.0，未上 PyPI、CI 未在真实 GitHub 上运行过、单一维护者、M5 冻结确认未执行——**还不是成熟产品**。进化计划按差距维度组织。

## 1. 差距矩阵（vs 四竞品的实测/源码证据）

| 维度 | domimap 现状 | 竞品参照 | 差距性质 |
|---|---|---|---|
| 分发 | 仅源码克隆/`pip install .`；无 PyPI | CBM 有一体化安装器与二进制；CodeGraph 是 npm 包 + VS Code 集成；graphify 可 `uv/pip install` | **高优先**：用户获取成本 |
| 语言覆盖 | Java 深度（Spring/MyBatis/Dubbo/RocketMQ/DDL）+ 文档多格式；TS/JS/Vue 基础 | CBM 162 语言（tree-sitter 内置）；CodeGraph ~30；graphify ~40 | 中：战略取舍（深度 vs 广度） |
| 增量 | `update` 手动触发（manifest 未变毫秒级 no-op） | CodeGraph 文件监听 300ms 增量 | 中 |
| 平台矩阵 | macOS 实测为主；CI 矩阵（ubuntu/macos × 3.11/3.13）已配置但从未在 GitHub 真跑 | 竞品多平台发布产物 | 推送后自动补齐一半 |
| 语义/跨语 | 词法 + 可选本地嵌入双路（RRF 融合 + 资格门）+ 长文档分段；检索级公开语料 50→70/140 | claude-obsidian 靠宿主模型生成内容（天然跨语） | 中（主体已补齐；答案层传导复测待跑） |
| 生态集成 | MCP stdio + CLI + Web UI，四客户端注册文档 | CodeGraph/Graphify 深度绑定各家 Agent 生态 | 中 |
| 验收闭环 | `release-check` 关闭（M5 冻结确认未执行，480×5×5 预算 ≈1.36 亿 token） | 竞品无此纪律 | 自设门槛，按 roadmap 走 |
| 社区 | 单人、无外部用户/贡献者 | 竞品有真实用户群 | 长期 |

## 2. 进化里程碑

### E1 分发就绪（推送当日即可完成）
- **内容**：PyPI 发布（0.5.0 起）；GitHub Release + tag 触发 [Trusted Publishing](https://docs.pypi.org/trusted-publishers/)（工作流已就位：`.github/workflows/pypi.yml`）；README 徽章与安装命令切换为 `pip install domimap`。
- **完成标准**：`pip install domimap && domimap doctor` 在干净环境可用；CI 三平台绿。

### E2 平台与语言扩展
- **平台**：推送后首个 GitHub Actions 运行即真实验证 ubuntu/macos × 3.11/3.13（本地已用 py3.9/3.13 × 有/无可选依赖模拟通过）；Windows 按需补 `py -3` 路径测试。
- **语言**：分两档——(a) 低成本广度：引入 tree-sitter 作为**可选**解析引擎（`domimap[crosslang]`），符号级 CALLS/CONTAINS 复用现有图模型（不动 Java 深度路径，保零核心依赖）；(b) 深度扩展按需逐语言做（像 Java 一样带 conf/prov 与文档泳道）。
- **完成标准**：新增语言有独立契约测试与夹具；Java 路径回归零变化。

### E3 语义层（主体已落地，2026-10-21）
- **已落地**（并行任务实测）：可选本地嵌入索引（bge-small-zh / fastembed，幂等离线建库）+ RRF 融合 + 融合资格门（定义性标识符/代码意图词时词法权威）——pub 23/97→36/97、dev 19/36→26/36 零回归；长文档分段（阈值 3500 / 段 1500 / 重叠 250）——检索级公开语料 50→70/140（doc 6→15、fresh 6→17），全项目最大单轮收益；文档意图语义召回限定 Doc/Knowledge 子池；查询期 LLM 重排实测**零效果**（GLM 片段零样本判断不敌 BM25 且多数 miss 在池外）——如实保留结论不保留默认开启。
- **剩余**：检索收益向答案层的传导复测（agent 引用纪律是当前主要损耗，见 product-query-discipline 的 instrumented 诊断）；构建期零模型调用的原则不变（enrich 为可选后置层且 conf=LLM 人工审定前不作事实）。
- **完成标准**：答案层公开语料正例 ≥26/32 且开发集不回退；负例拒答不劣化；无网络依赖（嵌入模型本地加载）。

### E4 增量与实时性
- 文件监听（watchdog 可选依赖或 stdlib 轮询）触发 `update`；目标对标 CodeGraph 的亚秒级单仓增量（我们已有 manifest 级 no-op 判定，缺触发器）。
- **完成标准**：保存文件 → 图更新 ≤2s（单仓）；CPU 空闲时零轮询开销。

### E5 生态与机器可读性
- `domimap schema`：输出节点/边/置信度语义的 JSON Schema（与 [knowledge-graph.md](knowledge-graph.md) 同源生成，防漂移）——让 AI 客户端不读源码即可理解图谱（产品任务，需按 AGENTS 建 task spec）。
- 客户端矩阵文档化（已有 docs/clients.md 基础）；评估 VS Code / JetBrains 侧接入。
- **完成标准**：schema 通过自身消费测试（喂给一个 Agent 正确回答节点语义问题）。

### E6 验收闭环（roadmap M5，产品纪律）
- 冻结确认跑（独立环境、预登记、盲化裁决、480×5×5 预算）→ 三指标对四竞品严格胜出 → `release-check` 打开 → 1.0。
- 用户已豁免独立评测环境（同会话执行）；预算与预算来源需在执行前确认。

## 3. 本轮（2026-10-21）已落地的改进
- 安全：UI DNS rebinding 读泄露修复（全部请求校验回环 Host）+ 契约测试；安全面复核结论（见任务 `evolution-quickwins`）。
- 分发：版本 0.5.0、PyPI Trusted Publishing 工作流、`domimap --version`。
- 文档：README 生产级 mermaid 架构图与查询数据流图；本文。
