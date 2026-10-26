# domimap 需求漂移分析与优先级纠正计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正 2026-10-22 至 10-26 期间项目相对 specs/product.md、requirements.json（R01–R14 + F1–F4）与 docs/roadmap.md 的需求漂移，并按"地基优先"顺序恢复交付路径。

**Architecture:** 本计划分两部分。第一部分是漂移分析（每条发现精确到 `文件:行`，全部经二次人工核验）；第二部分是纠正计划——3 个 P0 任务按 writing-plans 纪律给出完整 TDD 步骤，P1/P2 按技能范围检查规则拆为"任务卡"（精确文件/接口/验收/负例），各自开工时再展开为独立计划文档。

**Tech Stack:** Python 3.13（stdlib 优先），SQLite（store.db / knowledge.db / queries.db），MCP stdio，unittest。

**审计方法:** 规范基准（product.md / requirements.json / acceptance.json / progress.json / workflow.md / benchmark.md / roadmap.md）↔ 代码逐模块比对；5 个并行子审计（M1 基础 / M2 检索与入口 / M3 知识层 / M4-5 客户端与门禁 / 反馈闭环不变量）；关键 P0/P1 结论逐行抽验原文。`make verify` 实测：601 tests OK（skipped=2），spec-check `{"requirements":21, "acceptance_cases":49, "verified_cases":7}`。

## Global Constraints

摘自 AGENTS.md / specs/product.md / specs/workflow.md，逐条适用于本计划所有任务：

- Preserve R01–R14 and F1-C1–C4/F2–F4。Do not quietly drop clients, manual UI, persona/context, aging, knowledge maintenance, platform/restore work or the four-competitor quality gate.
- Before product behavior changes, create a small task spec and task manifest under `specs/tasks/`, using `specs/task-template.json`.
- Never modify held-out questions, labels, denominators, budgets, baseline versions or metrics to make domimap win. No filename/name-substring scoring, hidden fallback ranks.
- Do not weaken the checker to obtain a pass. `make release-check` must keep failing while required evidence or real competitor results are missing.
- A change to explicit user scope requires the user's explicit change of requirement（product.md 变更控制）。
- `verified` requires current source fingerprint, successful checks and readable hashed artifacts。
- Core can work offline. Never expose user data, credentials or source snapshots in public artifacts. Generated output under `out/`。

---

# 第一部分：漂移分析（精确到文件:行）

## 0. 结论摘要

**项目没有"跑偏到违规"——反作弊护栏、release gate、诚实状态登记全部完好；但确实"跑偏到了别处"。** 漂移集中在三件事：

1. **方向漂移**：production-readiness.md（10-24）列出的 4 个 P0 地基切片（D10 捕获统一 / D11 来源身份 / D12 原子发布 / 整库恢复）至今没有任何任务规格；同一时段 30 个新任务规格全部投给了 UI 工作台打磨、3 个可视化文档任务、以及一套约 2,900 行的新子系统"检索反馈进化闭环"。
2. **语义漂移**：R06 原义"依据变化→定位陈述→人工复核队列"（roadmap.md:86,143）被 5 个新案例 AC-R06-03..07 改写为"检索质量自我改进"；当前全部 9 个 verified 案例中 5 个来自这次改写，而 R06 原始案例 AC-R06-01/02 的实现代码**零生产接线**。
3. **"仅库级实现"漂移**：六个需求的能力以"有函数、有测试、无入口"的状态存在——`make test` 601 全绿掩盖了用户/Agent 根本无法触达它们的事实。

一句话：**护栏没破，路走岔了；上层越盖越多，地基 P0 一直空着。**

## 1. 真实状态快照（2026-10-26，实测）

| 维度 | 状态 | 证据 |
|---|---|---|
| 里程碑 | M0–M5 全部 `implementing` | specs/progress.json:4-9 |
| 验收案例 | 49 例中仅 7 例 `verified`（AC-R02-01、AC-R06-03..07、AC-R08-03），42 例 `implementing`（10-24 指纹失效批量降级，带 invalidation_reason） | specs/progress.json |
| 本地门禁 | `make verify` 601 tests OK（2 skipped）；`spec-check` 通过 | 本次实测 |
| 发布门禁 | `--release` 拒绝：`Release incomplete: M0`；`--stage M5` 拒绝：`Unverified dependency: M3` | 本次实测 |
| 未提交改动 | 79 个文件（17 modified + 62 untracked），+2,824 行已跟踪 diff | git status |
| 已知缺陷 | D10/D11/D12 开放（known-defects.md:27-29）；D6/D7 自 M0 登记至今无任务 | docs/known-defects.md |

## 2. 五类漂移（含逐行证据）

### 2.1 方向漂移：地基 P0 未动，向上堆叠 【最影响交付】

docs/production-readiness.md:51-60（2026-10-24）列出的 P0 清单与实际任务投入对照：

| P0 切片（production-readiness） | 对应缺陷 | 至今任务规格 |
|---|---|---|
| 来源捕获统一（scan/build 与证据同份字节） | D10 | **无** |
| workspace/repo/source 身份贯穿 | D11 | **无** |
| graph.json/coverage/manifest 与 generation 原子发布 | D12 | **无** |
| 整库导出恢复（证据+来源映射+知识） | R07 | **无** |

而 10-22 之后创建的 30 个任务规格（`ls specs/tasks/*.json` 时间戳）投向：检索质量 5 个（embedding-index / query-discipline / semantic-lane / doc-chunking / question-quality）、UI 与文案 7 个（workbench / opt50 / refusal-reason / stats-fresh / note-validation / 2×）、可视化文档 3 个、反馈闭环 6 个、闭环自查纠正 8 个（drift-correction-c0..c7）。**今天的 C0–C7"漂移纠正"是对反馈闭环子系统内部缺陷（F01–F10）的纠正——纠正的是绕路途中的坑，不是绕路本身**（out/drift-audit-2026-10-26/audit-and-correction-plan.md 开篇即写明审查目标是"核对 retrieval-feedback-evolution-plan 是否忠实实施"）。

具体地基缺陷（全部经代理 + 本人双重核验行号）：

- **[R02/D10] 普通 `build` 发布零证据图**：`domimap/__main__.py:101-105` 单仓/`--merge` 路径直接调 `graph.build()`（`domimap/graph.py:310-319`），从不构造 `EvidenceStore`；只有 `--discover` 才走 `batch.build_many → _publish`。`domimap/batch.py:74-77` 的捕获在另一条路径上。
- **[R02/D10] 同一文件两次读盘**：扫描读一次（`domimap/lite_scan.py:103-108`，utf-8/gb18030 解码），证据捕获再读一次（`domimap/store.py:57-58`，二进制），两读之间源被改写即产生"图来自版本 A、证据来自版本 B"。
- **[R01/D11] 来源身份 = `basename|rel`**：`domimap/batch.py:73-76` `label = os.path.basename(...)` → `store.capture_source(label, label + "|" + rel, ...)`；`domimap/source.py:16-74` 的 `SourceRegistry`（rid/rebind/sha256 内容版本）**零生产调用**，只有 tests/test_identity.py 引用。同 basename 两仓的 sources 行被 `ON CONFLICT(sid) DO UPDATE` 原地覆盖（`domimap/store.py:94-96`）。
- **[R01] route:/sql:/page: 节点 ID 不带仓/服务身份**：`domimap/graph.py:90,98,157`；`iface` 取命名空间末段（`domimap/lite_scan.py:465-466`），`com.a.OrderMapper.insert` 与 `com.b.OrderMapper.insert` 合并为同一 `sql:` 节点。
- **[R01] mtime+size 即事实内容版本**：`domimap/batch.py:40` `sig[rel] = [st.st_mtime_ns, st.st_size]`；`repo_changed`（:43-55）据此判"无变化"，`cp -p`/`touch -r` 后永久 no-op，合并图与源静默分叉。
- **[R03/D12] 代际切换后兼容文件非原子写**：`domimap/batch.py:79-82` `store.publish_graph(g)`（事务切 active）**之后**才 `_sh.copyfile(...)` graph.json（原地截断写，无 tmp/fsync），再直写 coverage.json（:152-153）；崩溃窗口内 store 读者见新代而 CLI/UI/MCP（`-g graph.json`）见旧图——混代。`manifest.json` 同样直写（:143-146）。
- **[R03/D1 残留] graph.json 单独丢失仍误报 no-op**：`domimap/batch.py:86-97` `_store_healthy` 只查 `active_generation()`+seeds，不查兼容副本；`tests/test_evidence_store.py:125-126` 的回归只删了 gen 文件+graph.json 两者。
- **[R02/R03] 捕获失败静默吞掉**：`domimap/batch.py:76-78` `except (OSError, ValueError): continue`，不进 coverage skipped 清单。

### 2.2 语义漂移：R06 被改写为另一个需求 【需要用户裁决】

- 原义（roadmap.md:86 "R06 依据变化定位到陈述，复核队列与反馈"；roadmap.md:143 "source/配置/推断规则到 claim 的依赖、变化摘要和待复核队列……"）＝ **知识声明层的依赖失效**。
- 新增 AC-R06-03..07（specs/acceptance.json，未提交 diff）＝ **检索质量观测/反馈/诊断/回放/受控进化**，配套 5 个新模块（observation 391 行 / feedback 748 / diagnosis 746 / replay 463 / storage 42）+ MCP 第 7 工具 + 11 个 CLI 子命令。
- 后果一：R06 标题下挂了 7 个案例，其中 5 个与原义无关；roadmap.md:102 仍写"21 项需求、44 个案例"（实际 49）。
- 后果二：当前 7 个 verified 案例中 5 个是这条新线，**注意力记账被新线主导**。
- 后果三：AC-R06-01/02 的原义实现是"仅库级"：`domimap/knowledge.py:240-271` `scan_dependencies`、`:232-238` `record_baseline`、`:274-284` `confirm_review` 仅被 tests/test_m3_review.py:19-62 与 tests/test_m3_r07.py:72-88 调用，无任何 build/update/CLI/UI/MCP 路径触发——真实工作区永远不会产生待复核项。
- 依 product.md 变更控制（"改变用户明确范围需用户明确变更需求"），这次改写**需要用户追认**：升级为正式 R15（推荐），或降级为实验特性。

### 2.3 "仅库级实现"漂移：功能存在但用户/Agent 不可达 【最隐蔽，绿灯掩盖】

`make test` 全绿，但以下能力没有任何入口（CLI 子命令清单见 `domimap/__main__.py:636-743`，无对应命令；MCP 7 工具无对应工具；UI 无对应路由）：

| 需求 | 仅库级实现 | 证据（函数/唯一调用者） |
|---|---|---|
| F3 可信 AGENTS/SOUL | `context.load_context` | `domimap/context.py:12`；`grep load_context domimap/ scripts/` → 0 生产调用者 |
| F4 历史查询 as_of | `Searcher.query(as_of=...)` | `domimap/search.py:284-286` 支持；`grep as_of domimap/__main__.py domimap/mcp.py domimap/ui.py` → **0 处** |
| F4-02 + R06-01/02 陈旧标记 | `claims_with_flags(current_digests)` | `domimap/knowledge.py:99-100` 生产调用恒不带 digests；`domimap/search.py:83` 只有测试传 |
| R05 修订/审定/撤回/历史 | `amend`/`withdraw`/`accept_claim`/`history` | `domimap/knowledge.py:164-205`；UI 只有 `POST /api/note/save`（submit，`domimap/ui.py:1142-1176`） |
| R07 备份/恢复/导入导出 | `backup`/`restore`/`export_markdown`/`import_markdown` | `domimap/knowledge.py:332-455`；无 CLI/MCP/UI（唯一 `.restore(` 是 queries.db 的 qrestore） |
| R01 来源注册 | `SourceRegistry` | `domimap/source.py:16` 死代码 |

验收文本因此字面不可执行：AC-R07-01 "when: 在线备份并在干净目录恢复"、AC-F4-01 "冻结 as_of"——用户没有可敲的命令。

### 2.4 过程护栏绕过：任务 manifest 全仓白名单 【R13 空转】

- `specs/tasks/retrieval-feedback.json`、`drift-correction-c0..c7.json`、`retrieval-observation/diagnosis.json` 共 11 份 manifest 的 `files` 字段是**同一份 79 文件清单**，包含 `specs/requirements.json`、`specs/acceptance.json`、全部兄弟 manifest（实测：79 files; has specs/acceptance.json: True）。
- `scripts/check_specs.py:198-204` 的 `--task` 范围检查（changed − allowed → 拒绝）随之失效：任何改动都在白名单内。对照良例：`product-ui-workbench.json` 3 文件、`production-boundaries.json` 18 文件。
- 规避有"理由"（retrieval-observation.md:164-166：登记并行任务仅为全 diff 范围检查），正确解法是单列一份 kind=umbrella 任务，而不是让每个切片都持有全仓钥匙。

### 2.5 新增写入面无门控：MCP `kg_feedback` 【P0，违反 roadmap M3 明文】

- roadmap.md:146 "MCP 写能力明确启用、与只读分开，服务端校验参数和目标范围"。现状：
  - `domimap/mcp.py:41-57` `kg_feedback` 无条件进入 `TOOLS`；`domimap/mcp.py:301-302` `tools/list` 返回全部；`serve(graph_path)`（:316）与 `Server.__init__(self, graph_path)`（:91）无任何开关参数。
  - `domimap/mcp.py:291` 注释仍写 `# These tools are read-only.`——对第 7 个工具已为假。
  - `domimap/mcp.py:217` handler 硬编码 `source="user_feedback"`，而 `domimap/feedback.py:26` `AUTHORITATIVE_SOURCES` 含 `user_feedback` → **任何 MCP 客户端（LLM Agent）可写入"用户判定"，直接主导命中率/覆盖率/诊断问题队列统计**（feedback.py:364-368, 371-387；diagnosis.py:139-144）。

## 3. 按需求逐项核查表

| 需求 | 状态 | 关键证据 |
|---|---|---|
| R01 身份 | **偏（地基）** | basename sid（batch.py:73-76）；route/sql/page 无身份（graph.py:90,98,157）；mtime 当版本（batch.py:40）；SourceRegistry 死代码；D11 开放 |
| R02 证据 | **偏（地基）** | 普通 build 零证据（__main__.py:101-105）；两读（lite_scan.py:103-108 vs store.py:57-58）；sha 只算 1MiB 前缀（store.py:35,59-61）；GBK 证据读回乱码（store.py:142）；捕获失败吞掉（batch.py:76-78）；D10 开放 |
| R03 构建恢复 | **偏（地基）** | store.db 内部代际协议**好**（store.py:186-219 + sha 校验 :230-238）；但 graph.json/coverage/manifest 非原子（batch.py:82,143-146,152-153）；graph.json 单丢误报 no-op（batch.py:86-97）；D12 开放 |
| R04 检索与图 | **偏（语义）** | impact 把 MENTIONS/BELONGS_TO 当反向依赖（graph.py:276-279 无边类型过滤；scenario.py:102 同）——"MENTIONS 不冒充因果"被违反；路径强度≤最弱边：全库无此概念；max_nodes 预算只有 MCP 执行（mcp.py:242-253），CLI（__main__.py:190）与 UI（ui.py:1371）无界 |
| F2 手工搜索 | **偏（入口分叉）** | 无共享应用服务：UI `expand:False`（ui.py:1242）vs CLI/MCP 默认 True；`kg_doc_search` 绕过 run_query 且 top_k=8/budget=6000/无 seeds（mcp.py:255），CLI/UI 无对应命令；UI `/api/search` 无 try/except，异常→无 HTTP 响应（ui.py:1241-1243） |
| F3 可信上下文 | **偏（不可达）** | context.py 37 行仅函数级实现，零调用者；默认 `trusted=[root]` 自信任（context.py:15）；无变更检测/嵌套裁决/逐客户端记录；docstring "一层嵌套" vs os.walk 全深度（:13 vs :19） |
| F4 时间策略 | **偏（半实现）** | as_of 核心在（search.py:368-381）但无入口；**默认查询不排除过期/被替代文档**（资格门槛只在 as_of 分支内，:368-381）；touch/copy 在图平面刷新 first_seen（lite_scan.py:135-140 → graph.py:178 → search.py:526-535）；time_note 计算了从不展示（search.py:657 vs _render :685-699）；store 平面的 content_first_seen min 语义是好的（store.py:88-92） |
| F1-C1..C4 四客户端 | **停滞** | 无 `domimap connect` 类命令（__main__.py:628-743）；四客户端均手工登记（docs/clients.md:9-12）；无一测试驱动真实客户端二进制；DSH 身份文档自相矛盾（clients.md:12 vs :14）；m4-clients-c1.md 自认生命周期脚本缺失。Codex/DSH blocked 属外部阻塞、登记诚实 |
| R05 知识保存 | **半（仅库级）** | submit/幂等/乐观锁/修订快照/中断注入好（knowledge.py:133-191）；但 `amend` 清空 claims 状态且不清理 claim_bindings（:176-184，idx 键位错配可压制复核）；无审定事件表；claims 无支持/反对分栏（:28-30）；withdraw/accept 无存在性检查（:193-205）；UI 保存重挂致 BM25 统计双计（ui.py:1169 + search.py:85-105） |
| R06（原义） | **偏（不可达）** | 见 2.2；scan_dependencies 仅测试调用；依赖只有证据 sha 一类（无 source 版本/配置/推断规则边，无变化摘要） |
| R06（新义 03-07） | 实现良好 | 隐私默认不存原文（HMAC，observation.py:72-73,80-112）；fail-open（:339-346）；`DOMIMAP_OBSERVE=0`（:67-69）；AI 白名单+预算+冷却（diagnosis.py:22-26,554-651）；回放冻结/门槛完整（replay.py:108-110,277-287,348-360）；benchmark 零触碰。遗留：部分删除（ids/before）不要求备份（feedback.py:492-498 vs AC-R06-04 文本）；RECORD_LATENCY_BOUND_S=4.0 仅注释（observation.py:27）；启用=只记台账，排序代码本身无运行时门（结构性说明） |
| R07 导出恢复 | **偏（缺整库）** | knowledge.db 表级备份恢复好（knowledge.py:332-417 + test_knowledge_safety.py:99-224）；无整库（证据 blob+图+来源映射）恢复；无冲突预览 API（:447-453）；无导出目录回灌防护（无 note_id front-matter 检测）；全部无 CLI 入口 |
| R08 信任边界 | **基本守住，1 个 P0** | UI：回环绑定/Host+Origin/CSP `default-src 'none'`/无 innerHTML/1MiB body（ui.py:1102-1104,1219-1233,1146）；MCP：有界帧/同源 schema 校验/isError（mcp.py:265-276,69-87,158-167）；符号链接越界拒绝（lite_scan.py:63-70）。**例外＝kg_feedback 无门控（2.5）**；queries.db/queries.key 落在图旁目录，.gitignore 无全局兜底（自定义 -g 路径可能把查询日志带进 git） |
| R09 平台矩阵 | 偏（卫生） | pyproject `requires-python >=3.9` vs CI 只测 3.11/3.13（ci.yml:21-22）vs roadmap 3.11–3.14 |
| R10 迁移恢复 | 偏（卫生） | 三个 DB 无 `PRAGMA user_version`/迁移表；doctor 不开任何 DB（__main__.py:37-84） |
| R11 分发 | 基本好 | install_check.sh 干净目录安装烟测进 CI（ci.yml:32-33）；Actions 浮动 tag 未钉 SHA（ci.yml:24-25，pypi.yml:12-13,23） |
| R12/R13 | R12 待做；R13 **被 2.4 绕过** | 检查器本身未削弱；manifest 喂了全仓清单 |
| R14 四竞品 | **护栏完好，未完成（如实）** | evaluate.py "missing is not zero"（:60-61）、Bonferroni α=0.05/12（:163）、严格胜出（:184-187）、synthetic→diagnostic_only（:188,215）；`git diff HEAD -- benchmarks/` 为空；release-check 如实拒绝。卫生：benchmarks/TWELVE_OF_TWELVE_RESULT.json 文件名夸大（hit_at_5 0.644 < 0.80 底线，grade 字段如实） |

## 4. 未漂移——守住的护栏（应保持）

- 反作弊红线全绿：无 gold 泄漏、无文件名子串判分（F02 纠正后回放甚至"同文件错节点=miss"）、benchmarks/ 零改动、无隐藏回退排序。
- 诚实记账：progress 批量降级带原因；release-check 照常拒绝；平台/客户端矩阵不虚报；keep-itemproduct 双 MISS 保留不改 gold。
- 隐私默认：查询原文默认不落盘（HMAC 摘要 + `DOMIMAP_KEEP_QUERIES=1` 显式保留 + `DOMIMAP_OBSERVE=0` 关闭）；queries.key 0600。
- 离线核心：新模块纯 stdlib、无后台线程/调度器、无默认网络；嵌入/重排/桥接全部 env 门控（semantic_bridge.py:39-43 / embedding.py:45-48 / llm_rerank.py:37-40）。
- store.db 代际协议（tmp→fsync→rename→校验→sha→单事务切 active）与证据不可变读取（available:false 而非重定向）。

## 5. 卫生问题清单（P2 批处理）

1. 计数漂移：ui.py:3-4 "7+6=13"（实际 8+6=14，fbhist 后加）；tests/test_ui_workbench.py:25-27 少列"反馈与历史"；__main__.py:24 与 ui.py:416 "6 工具"；docs/production-readiness.md:39 "六工具"；roadmap.md:102 "44 个案例"。
2. CHANGELOG.md（未提交 diff）：空的 `### 已实现` 标题紧接 `### 已实现（原型演进…）` 重复标题；一处写 "597 tests OK"（现为 601）。
3. acceptance.json：AC-R06-07 追加在文件末尾脱离 R06 区段；两文件缺末尾换行。
4. context.py:13 docstring 与 os.walk 行为不符；CLI impact 打印 dst/conf 错位（__main__.py:196）。
5. scenario_req 手工拼接扩展词、绕过 EXPANSION_TOKEN_WEIGHT（scenario.py:33-43）。
6. .gitignore 缺全局 `queries.db`/`queries.db-*`/`queries.key`；qexport/diagnose --out 无"勿发布"提示。
7. benchmarks/TWELVE_OF_TWELVE_RESULT.json 文件名 vs 内容。
8. Actions 未钉 SHA；requires-python 与 CI 矩阵不一致；DB 无 user_version；doctor 不查 DB。
9. store.py:59-61 sha 只算 1MiB 前缀；store.py:142 GBK 读回乱码。
10. DSH 身份文档矛盾（docs/clients.md:12 vs :14）。

---

# 第二部分：优先级计划

## 优先级排序原则

1. production-readiness.md 自己推导的架构顺序：来源身份/版本 → 证据 ID 稳定 → 确认写入不丢 → 限额内检索 → 入口可重复。**先修地基，再铺入口。**
2. 用户明确四能力（四客户端 / 无模型手工检索 / 可信上下文 / 时间策略）不得继续空转——凡"仅库级"的能力，优先接线而非重写。
3. 规范诚实性优先于新功能：R06 语义裁决、manifest 边界、写门控三件事都很小，先做，让后续记账可信。

## 排序总表

| # | 任务 | 类型 | 需求 | 规模 |
|---|---|---|---|---|
| T1 | R06 范围裁决与 AC 迁往 R15 | 规范 | R06/R13 | 半天 |
| T2 | MCP 写工具显式启用 + 来源降级 | 代码 P0 | R08/M3 | 半天 |
| T3 | 任务 manifest 边界恢复（umbrella） | 过程 P0 | R13 | 半天 |
| T4 | D10 捕获统一：普通 build 走证据契约 | 地基 P1 | R02/R03 | 1-2 天 |
| T5 | D11 来源身份：SourceRegistry 接线 + 节点 ID 带身份 | 地基 P1 | R01 | 2-3 天 |
| T6 | D12 原子发布 + 内容哈希增量 | 地基 P1 | R03 | 1-2 天 |
| T7 | 整库导出恢复 | 地基 P1 | R07 | 2 天 |
| T8 | 公共应用服务（query/impact/错误/热重载/默认参） | 入口 P1 | product#6/F2 | 2 天 |
| T9 | as_of 入口化 + 默认资格门槛 + time_note 展示 | 入口 P1 | F4 | 1 天 |
| T10 | F3 接线（显式 trusted、变更检测、嵌套裁决） | 入口 P1 | F3 | 1-2 天 |
| T11 | 原义 R06 + F4-02 接线（baseline/扫描复核/陈旧标记） | 入口 P1 | R06/F4-02 | 2 天 |
| T12 | 知识层 CLI/MCP 写入口 + amend 修复 | 入口 P1 | R05 | 1-2 天 |
| T13 | impact 因果边过滤 + 最弱边强度 | 语义 P1 | R04 | 1 天 |
| T14 | `domimap connect` 四客户端 | 客户端 P2 | F1-C1..C4 | 3-5 天 |
| T15 | 卫生批处理（§5 清单） | 卫生 P2 | 多项 | 1 天 |

依赖：T1→T2→T3 先行（恢复记账诚实性）；T4→T5→T6→T7 是地基链；T8 是 T9/T11/T12 的汇合点（先做 T8 使入口接线有单点）；T13 独立可并行；T14 依赖 T8 完成后的服务面。

---

### Task 1: R06 范围裁决与 AC 迁往 R15（规范变更，无产品代码）

**用户裁决点（Step 0，二选一）：**
- **(A)（推荐）追认为正式需求 R15「检索质量反馈与受控进化」**：闭环工作真实、质量高、隐私纪律好；迁册后诚实挂在明处。
- (B) 降级为实验特性：AC-R06-03..07 移出验收登记（标注 experimental），MCP 工具默认隐藏（与 T2 合并），后续不再投入直至地基完成。

以下步骤按 (A) 编写；(B) 时把"迁往 R15"换成"移入 experiments 附录"并跳过证据重跑。

**Files:**
- Modify: `specs/requirements.json`（R06 cases 回 2 条；新增 R15 条目）
- Modify: `specs/acceptance.json`（5 个案例 id 改 AC-R15-01..05、requirement→R15、归位排序、补末尾换行）
- Modify: `specs/progress.json`（键名同步；5 例降 implementing 并注明重证）
- Modify: `docs/roadmap.md:102`（44→49）、`docs/roadmap.md` §5 表（R14 行后加 R15 行）
- Create: `specs/tasks/spec-rehome-r15.json` / `.md`
- Test: `tests/test_spec_contracts.py`

**Interfaces:**
- Produces: R15 = `{"id":"R15","title":"检索质量反馈与受控进化","milestones":["M3"],"cases":["AC-R15-01".."AC-R15-05"]}`；AC-R15-0N 的 given/when/then 文本与原 AC-R06-0(N+2) 逐字相同（内容不变，只换归属）。

- [ ] **Step 1: 写失败测试** — 在 `tests/test_spec_contracts.py` 的 `TestSpecContracts` 中新增（该文件现有测试直接读 `ROOT` 真实文件，见 :41-54 模式）：

```python
    def test_r06_keeps_original_scope_and_r15_hosts_retrieval_feedback(self):
        req = json.loads((ROOT / "specs/requirements.json").read_text(encoding="utf-8"))
        by_id = {r["id"]: r for r in req["requirements"]}
        self.assertEqual(by_id["R06"]["cases"], ["AC-R06-01", "AC-R06-02"])
        self.assertEqual(by_id["R15"]["cases"],
                         ["AC-R15-0%d" % i for i in range(1, 6)])
        acc = {c["id"]: c for c in json.loads(
            (ROOT / "specs/acceptance.json").read_text(encoding="utf-8"))["cases"]}
        self.assertTrue(all(acc[c]["requirement"] == "R15"
                            for c in by_id["R15"]["cases"]))
        self.assertFalse({"AC-R06-0%d" % i for i in range(3, 8)} & set(acc))
```

- [ ] **Step 2: 运行确认失败** — `python3 -B -m unittest tests.test_spec_contracts -v`；预期 FAIL（R06 cases 为 7 条、无 R15）。

- [ ] **Step 3: 建任务规格** — `specs/tasks/spec-rehome-r15.json`（模板字段 + 本节 Files 全列表，state=implementing，requirements=["R13"]，acceptance_cases=["AC-R13-01"]）与同名 `.md`（关联需求、动机=2.2 节结论、回滚=反向重命名）。

- [ ] **Step 4: 改三个规范 JSON**
  - requirements.json：R06.cases → `["AC-R06-01","AC-R06-02"]`；R14 条目后新增 R15（Interfaces 处的字面量，逐字）。
  - acceptance.json：`AC-R06-03→AC-R15-01`、`04→02`、`05→03`、`06→04`、`07→05`；每个改 `"requirement": "R15"`；把原文件末尾的 AC-R15-05 移到 AC-R15-04 之后；文件末尾补换行。
  - progress.json：cases 键同步重命名；5 例 `state` 改 `"implementing"`，`invalidation_reason` = `"2026-10-26: re-homed AC-R06-0N→AC-R15-0M; evidence case_id 字段需在新 ID 下重跑"`；旧 evidence 移入 `historical_evidence`。

- [ ] **Step 5: 改 roadmap 两处** — :102 "21 项需求、44 个案例"→"21 项需求、49 个案例"（R15 使需求数变为 22，同步改"22 项需求、49 个案例"）；§5 表 R14 行后加 `| R15 | 检索质量反馈与受控进化（观测/反馈/诊断/回放/启用门槛） | M3 | 冻结样本回放三轮 + activated lineage + 统计口径分列 |`。

- [ ] **Step 6: 重跑证据恢复 verified** — 依次执行（命令取自 C0–C7 任务规格的"验证"节）：
```bash
python3 -B -m unittest tests.test_observation tests.test_feedback tests.test_diagnosis tests.test_evolution_replay tests.test_feedback_lifecycle -v
python3 -B scripts/refresh_evidence.py spec-rehome-r15 HEAD   # 两遍纪律：第二遍收敛指纹
```
  为 5 例生成 `out/verification/AC-R15-0N.json`（workflow.md §5 格式：schema_version/case_id/outcome/source_fingerprint/command/exit_code/environment/artifacts+sha256/limitations）；progress 回 `verified`。

- [ ] **Step 7: 验证** — `make spec-check && python3 -B -m unittest tests.test_spec_contracts -v`；预期全 PASS（49 案例、R06=2、R15=5）。

- [ ] **Step 8: Commit** — `git add specs/ tests/test_spec_contracts.py docs/roadmap.md && git commit -m "spec: R06 回归原义（知识依赖失效复核），检索反馈闭环迁册为 R15（用户裁决路径 A）"`

---

### Task 2: MCP 写工具显式启用 + 转达来源降级（P0）

**Files:**
- Modify: `domimap/mcp.py:62-64`（TOOLS 后加常量与函数）、`:70`（docstring）、`:91-94`（Server.__init__）、`:158-167`（call 门控）、`:217`（source）、`:291`（注释）、`:301-302`（tools/list）、`:316-317`（serve 签名）
- Modify: `domimap/__main__.py:24`（help）、`:216-218`（cmd_serve）、`:660`（serve 子命令加 flag）
- Modify: `domimap/feedback.py:24-25`（SOURCE_VALUES 加 agent_relay；AUTHORITATIVE_SOURCES 不动）
- Modify: `domimap/ui.py:416`（文案）
- Test: Create `tests/test_mcp_write_gate.py`；Modify `tests/test_mcp_desc.py:42-45`

**Interfaces:**
- Produces: `mcp.visible_tools(enable_write) -> list[dict]`；`Server(graph_path, enable_write=False)`；`serve(graph_path, enable_write=False)`；`feedback.SOURCE_VALUES += ("agent_relay",)`（非权威）。
- Consumes: 现有 `_response(srv, req)`、`Server.call(name, args)` 的 isError 契约（mcp.py:158-167）、`FeedbackStore.submit`（feedback.py:124）。

- [ ] **Step 1: 写失败测试** — 新建 `tests/test_mcp_write_gate.py`（夹具模式照 tests/test_production_boundaries.py:24-34）：

```python
"""MCP 写能力显式启用（roadmap M3：写能力明确启用、与只读分开；转达判定不作人源）。"""
import tempfile
import unittest
from pathlib import Path

from domimap import mcp
from domimap.feedback import FeedbackStore, AUTHORITATIVE_SOURCES
from domimap.graph import Graph
from domimap.observation import run_query


class TestMcpWriteGate(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dm-mcp-write-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        g = Graph()
        g.add_node("doc:fixture", "Doc", "fixture", "input.md", {"text": "version"})
        g.save(str(self.root / "graph.json"))
        self.graph = str(self.root / "graph.json")

    def _names(self, srv):
        r = mcp._response(srv, {"jsonrpc": "2.0", "id": 1,
                                "method": "tools/list", "params": {}})
        return {t["name"] for t in r["result"]["tools"]}

    def test_default_server_lists_only_six_read_tools(self):
        names = self._names(mcp.Server(self.graph))
        self.assertEqual(len(names), 6)
        self.assertNotIn("kg_feedback", names)

    def test_enable_write_lists_feedback_tool(self):
        self.assertIn("kg_feedback",
                      self._names(mcp.Server(self.graph, enable_write=True)))

    def test_disabled_write_call_is_explicit_error(self):
        srv = mcp.Server(self.graph)
        r = srv.call("kg_feedback",
                     {"event_id": "qe:" + "0" * 24, "relevance": "hit"})
        self.assertTrue(r["isError"])
        self.assertIn("write_disabled", r["content"][0]["text"])

    def test_enabled_write_records_non_authoritative_relay_source(self):
        srv = mcp.Server(self.graph, enable_write=True)
        _, obs = run_query(self.graph, srv.s, "fixture", "mcp",
                           {"top_k": 6, "seeds": srv.seeds})
        qid = obs["event_id"]
        r = srv.call("kg_feedback", {"event_id": qid, "relevance": "hit"})
        self.assertFalse(r["isError"], r)
        store = FeedbackStore(str(self.root / "queries.db"))
        rows = store.db.execute(
            "SELECT source FROM feedback WHERE event_id=?", (qid,)).fetchall()
        self.assertEqual([row[0] for row in rows], ["agent_relay"])
        self.assertNotIn("agent_relay", AUTHORITATIVE_SOURCES)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败** — `python3 -B -m unittest tests.test_mcp_write_gate -v`；预期 4 项全 FAIL（TypeError: Server() 无 enable_write 参数 / tools/list 含 kg_feedback / 无 write_disabled / source 为 user_feedback）。

- [ ] **Step 3: 实现** — `domimap/mcp.py`：

```python
# TOOLS 列表之后（约 :62）
WRITE_TOOLS = frozenset({"kg_feedback"})


def visible_tools(enable_write):
    """tools/list 只公布当前实例允许调用的工具：默认只读，写工具按显式启用出现。"""
    return [t for t in TOOLS if enable_write or t["name"] not in WRITE_TOOLS]
```

`Server.__init__`（:91-94）：
```python
    def __init__(self, graph_path, enable_write=False):
        self.graph_path = graph_path
        self.enable_write = bool(enable_write)
        self._mtime = None
```
`Server.call`（:158）开头加门控（在 try 之前，直接走既有错误形态）：
```python
    def call(self, name, args):
        if name in WRITE_TOOLS and not self.enable_write:
            return {"content": [{"type": "text",
                                 "text": "错误: 写工具未启用（write_disabled）；以 --enable-write 启动后可用"}],
                    "isError": True}
```
`_dispatch` kg_feedback 分支（:217）：`source="user_feedback"` → `source="agent_relay"`。
`_response`（:291-292）：注释改 `# Notifications never get a reply or a tool execution; write tools are gated in call().`；:302 `result = {"tools": visible_tools(srv.enable_write)}`。
`serve`（:316-317）：
```python
def serve(graph_path, enable_write=False):
    srv = Server(graph_path, enable_write=enable_write)
```
`:70` docstring "six public tools" → "public tools"。`domimap/feedback.py:24-25`：
```python
SOURCE_VALUES = ("user_feedback", "human_annotation", "dev_gold", "rule_check",
                 "ai_suggestion", "agent_relay")
```
`domimap/__main__.py`：
```python
def cmd_serve(args):
    from domimap.mcp import serve
    serve(args.graph, enable_write=args.enable_write)
```
:660 处：
```python
    sv = with_g(sub.add_parser("serve"))
    sv.add_argument("--enable-write", action="store_true",
                    help="启用写工具 kg_feedback（默认只读；反馈以 agent_relay 来源记录，不进权威统计）")
    sv.set_defaults(fn=cmd_serve)
```
:24 help 改 `MCP stdio 服务器（6 个只读 kg_* 工具；--enable-write 加 kg_feedback）`；`domimap/ui.py:416` 文案同步。

- [ ] **Step 4: 跑测试通过** — `python3 -B -m unittest tests.test_mcp_write_gate tests.test_mcp_desc tests.test_production_boundaries -v`；预期全 PASS（`mcp.TOOLS` 仍 7 项，test_mcp_desc:42-45 不需改名单；如需，加一行 `self.assertEqual(len(mcp.visible_tools(False)), 6)`）。

- [ ] **Step 5: 全量回归 + 提交** — `make test && make spec-check`；`git add domimap/mcp.py domimap/__main__.py domimap/feedback.py domimap/ui.py tests/test_mcp_write_gate.py tests/test_mcp_desc.py && git commit -m "feat(mcp): kg_feedback 写工具显式启用门控，转达判定降为非权威 agent_relay 来源（roadmap M3 写能力与只读分离）"`

---

### Task 3: 任务 manifest 边界恢复（R13，umbrella 模式）

> **执行时细化（2026-10-26）**：T0 已将 79 文件批次提交入库，"为并行未提交文件做全 diff 检查"的 umbrella 需求消失，故不再新建 umbrella-worktree 任务。lint 规则定稿为三类 `kind`：`slice`（默认）禁规范文件与兄弟 manifest；`spec-change` 允许规范与兄弟 manifest、禁 `domimap/` 产品代码（T1 本身即此类）；`umbrella` 须 `reason`（两份历史发布净化任务归此类）。实际裁剪 20 份（原估 11 份：另有 6 份历史 manifest 也列有并行兄弟条目）。

**Files:**
- Modify: `scripts/check_specs.py`（check_task 内 + main() 加全量 lint）
- Create: `specs/tasks/umbrella-worktree-2026-10-26.json` / `.md`（kind=umbrella，持有现 79 文件清单）
- Modify: 11 份 mega-list manifest 裁剪回各自 .md「## 文件」节所列文件（retrieval-observation / retrieval-feedback / retrieval-diagnosis / retrieval-evolution-pilot / retrieval-evolution-replay / drift-correction-c0..c7）
- Test: `tests/test_spec_contracts.py`

**Interfaces:**
- Produces: `check_specs.NORMATIVE_SPECS`（frozenset）、`check_specs.check_manifest_bounds(name, task)`（非 umbrella manifest 不得白名单规范文件与兄弟 manifest）。
- Consumes: 现有 `check_task`（:180-204）、`load()`、main() 的 validate 流程。

- [ ] **Step 1: 写失败测试** — `tests/test_spec_contracts.py` 加两个测试。契约级（临时树，模式照 :118-136）：

```python
    def test_manifest_cannot_whitelist_normative_specs_or_siblings_unless_umbrella(self):
        req, cases, _ = specs.validate(self.root)
        cid = next(iter(cases))
        task = {"id": "identity", "state": "implementing",
                "spec": "specs/tasks/identity.md",
                "requirements": [cases[cid]["requirement"]],
                "acceptance_cases": [cid],
                "files": ["domimap/x.py", "specs/acceptance.json",
                          "tests/test_x.py"],
                "test_files": ["tests/test_x.py"]}
        self.write("specs/tasks/identity.md", "fixture")
        self.write("specs/tasks/identity.json", task)
        with self.assertRaisesRegex(ValueError, "normative"):
            specs.check_task(self.root, "specs/tasks/identity.json", req, cases)
        task["files"] = ["domimap/x.py", "specs/tasks/other.json",
                         "tests/test_x.py"]
        self.write("specs/tasks/identity.json", task)
        with self.assertRaisesRegex(ValueError, "task manifests"):
            specs.check_task(self.root, "specs/tasks/identity.json", req, cases)
        task["kind"] = "umbrella"
        self.write("specs/tasks/identity.json", task)
        specs.check_task(self.root, "specs/tasks/identity.json", req, cases)  # 不再抛
```

仓库级（真实文件，先红后绿）：

```python
    def test_real_task_manifests_are_bounded_slices(self):
        for manifest in sorted((ROOT / "specs/tasks").glob("*.json")):
            task = json.loads(manifest.read_text(encoding="utf-8"))
            specs.check_manifest_bounds(str(manifest.relative_to(ROOT)), task)
```

- [ ] **Step 2: 运行确认失败** — `python3 -B -m unittest tests.test_spec_contracts -v`；契约级 AttributeError（无 check_manifest_bounds）；仓库级同。

- [ ] **Step 3: 实现检查器** — `scripts/check_specs.py` 顶部常量 + 函数（放在 check_task 之前）：

```python
NORMATIVE_SPECS = frozenset({
    "specs/product.md", "specs/requirements.json", "specs/acceptance.json",
    "specs/benchmark.md", "specs/workflow.md", "benchmarks/protocol.json",
})


def check_manifest_bounds(name, task):
    """切片 manifest 不得白名单规范文件或兄弟 manifest；跨片全 diff 检查走 kind=umbrella。"""
    if task.get("kind") == "umbrella":
        return
    files = set(task.get("files", []))
    normative = sorted(files & NORMATIVE_SPECS)
    if normative:
        raise ValueError("Task whitelists normative specs (use kind=umbrella): "
                         + ", ".join(normative))
    own = {name, task.get("spec", "")}
    siblings = sorted(f for f in files
                      if f.startswith("specs/tasks/") and f not in own)
    if siblings:
        raise ValueError("Task whitelists other task manifests (use kind=umbrella): "
                         + ", ".join(siblings[:5]))
```

check_task 的 `for path in files:` 循环（:196-198）之后加 `check_manifest_bounds(name, task)`。main() 里 `req, cases, progress = validate(...)`（:218）之后加全量 lint：

```python
        for manifest in sorted((ROOT / "specs/tasks").glob("*.json")):
            check_manifest_bounds(str(manifest.relative_to(ROOT)),
                                  load(manifest))
```

- [ ] **Step 4: 建 umbrella 并裁剪 11 份 manifest** —
  - `specs/tasks/umbrella-worktree-2026-10-26.json`：`kind:"umbrella"`，`files` = 现 79 文件清单（从 retrieval-feedback.json 复制）+ `tests/test_spec_contracts.py`，`requirements:["R13"]`，`acceptance_cases:["AC-R13-01"]`，`test_files:["tests/test_spec_contracts.py"]`；.md 说明"仅为 AC-R13-01 全 diff 范围检查登记当前未提交工作区"。
  - 裁剪（各 .md「## 文件」节为准确来源）：c1→`domimap/feedback.py, domimap/observation.py, tests/test_feedback_lifecycle.py, specs/tasks/drift-correction-c1.{json,md}`；c2→`domimap/observation.py, tests/test_observation.py, c2.{json,md}`；c3→`domimap/feedback.py, domimap/__main__.py, domimap/ui.py, tests/test_feedback.py, c3.{json,md}`；c4→`domimap/diagnosis.py, tests/test_diagnosis.py, c4.{json,md}`；c5→`domimap/replay.py, domimap/__main__.py, tests/test_evolution_replay.py, c5.{json,md}`；c6→`domimap/mcp.py, domimap/__main__.py, domimap/ui.py, domimap/schema.json, tests/test_feedback.py, tests/test_mcp_desc.py, c6.{json,md}`；c7→`specs/tasks/drift-correction-c7.{json,md}, tests/test_evolution_replay.py, tests/test_identifier_ranking.py`；c0→`kind:"umbrella"`（其 .md 明言要改六份兄弟任务 json 的 state 字段 + progress.json + 两份文档，属跨片状态纠正）；retrieval-observation/feedback/diagnosis/evolution-pilot/evolution-replay/identifier-boost-scope→按各自 .md「## 文件」节照抄。
  - 注意：check_task 的 allowed 集合含 `{name, task["spec"], "specs/progress.json"}`（:202），progress 不必列入 files。

- [ ] **Step 5: 验证** — `make spec-check && python3 -B -m unittest tests.test_spec_contracts -v && python3 -B scripts/check_specs.py --task specs/tasks/drift-correction-c2.json --base HEAD`；预期全 PASS。

- [ ] **Step 6: Commit** — `git add scripts/check_specs.py specs/tasks/ tests/test_spec_contracts.py && git commit -m "spec(R13): 切片 manifest 边界检查——规范文件/兄弟 manifest 需 kind=umbrella；11 份全仓白名单裁剪回各自切片，全 diff 检查归 umbrella-worktree"`

---

## P1 任务卡（各自开工时展开为独立计划文档）

> 按 writing-plans 技能的范围检查规则：以下每张卡是独立子系统，值得各自的完整计划。这里锁定范围/接口/验收/负例，防再次漂移。

### Task 4: D10 捕获统一（R02/R03）
范围：`domimap/__main__.py:101-105`（cmd_build 单仓/merge 路径改走 `batch._publish` 或提取其等价函数）、`domimap/batch.py:74-82`、`domimap/lite_scan.py:103-108`、`domimap/store.py:57-58`。接口：`capture_source` 增加可选 `raw: bytes` 参数（调用方单次读盘后同时供哈希/解析/片段）；`build()` 返回后保证 `store.db` 存在且覆盖全部摄入文件。验收（AC-R02-01/02、AC-R03-01 方向）：① `domimap build tests/fixtures/mini -o out` 后 `read_evidence` 可读任意候选节点证据（新负例：缺证据即 fail）；② 扫描与捕获之间换源，图与证据不得来自不同版本（新增回归：monkeypatch 二次 open 抛错）；③ `update` 在普通 build 产物上不再 exit 5。负例：空仓、只读目录、坏 JSON 源。回滚：revert cmd_build 分支。禁止：顺手改 seeds/评分。

### Task 5: D11 来源身份（R01）
范围：`domimap/source.py`（SourceRegistry 接线）、`domimap/batch.py:73-76`、`domimap/graph.py:90,98,157,175-181`、`domimap/store.py:94-96,154-171`。接口：registry 持久化于工作区 meta 表（rid = 显式注册时生成，重绑记录）；节点 ID 统一 `kind:<rid>:…`；`evidence_map` 按 sid 解析。验收（AC-R01-01/02 方向）：同 basename 两仓并行 build→discover 不串接（新夹具 repo-a/repo-b 同名）；`sql:OrderMapper.insert` 两命名空间不合并；根重绑后旧 ev_id 仍可读。负例：未注册根、重复 rid、歧义链接显式拒绝（沿用现状"不猜"）。兼容：旧图只有 rel——按 rel 加载并显式标 `identity:"legacy"`，不静默升级。

### Task 6: D12 原子发布 + 内容哈希增量（R03）
范围：`domimap/batch.py:40,43-55,79-82,143-153`、`domimap/store.py`（如需导出 hash 接口）。接口：`publish_derived(out_dir, rec)` = graph.json/coverage/manifest 各自 tmp+fsync+rename，顺序在切 active **之前**；`repo_signature` 改 `sha256(前缀)`（T4 后字节已在手）+ mtime 仅作跳过提示。验收（AC-R03-01/02 方向）：任一点 kill -9 只见完整同代（新故障注入测试：copyfile 中途抛错）；graph.json 单独删除后 `update` 重建而非 no-op（补 D1 残留回归）；`cp -p` 同尺寸改写被内容哈希抓出。负例：磁盘满（ENOSPC 注入）、两构建者并发。

### Task 7: 整库导出恢复（R07）
范围：新 `domimap/workspace.py`（或并入 batch）：打包 store.db blob 根 + gens/ + sources 映射 + knowledge.db + queries.db(可选) 为单一 zip/目录，v1 清单含逐件 sha；`domimap/__main__.py` 新子命令 `export-workspace` / `restore-workspace`。验收（AC-R07-01）：在线导出→空目录恢复→历史 ev_id 可读、笔记/修订/审定/范围可检索（M3 出口演练脚本化）。负例：缺件/坏哈希拒绝、恢复不覆盖已有目标（沿 D9 语义）、路径穿越拒绝。回滚：命令级，无格式迁移。

### Task 8: 公共应用服务（product#6/F2）
范围：新 `domimap/service.py`；三入口改调：`__main__.py:136-196`、`mcp.py:154-262`、`ui.py:1235-1261,1361-1390`。接口：`AppService(graph_path)` 提供 `query(text, entry, **overrides)`（默认 top_k=6/expand=True/budget=3800/min_cov=0.3/as_of=None 一次性定义）、`impact(symbol, depth)`（默认 max_nodes=200）、统一错误→契约映射（refused/invalid/unavailable）、mtime 热重载（沿 mcp.py:128-136 移植给 UI）。验收：`kg_doc_search` 与新 CLI `domimap doc` 共用同参（消除 mcp.py:255 的 8/6000/无 seeds 特例）；UI 异常→HTTP 500 JSON（修复 ui.py:1241-1243 无响应）；tests/test_m2_shared.py 扩展断言 impact 三入口同 partial 语义。负例：坏参同错、热重载中查询不半新半旧。

### Task 9: as_of 入口化 + 默认资格门槛（F4）
范围：`domimap/search.py:368-381`（资格谓词提出 as_of 分支：superseded_by 与已过期 valid_until 默认排除并渲染标注，as_of 只挪时钟）、`:685-699`（_render 输出 time_note/valid_until）；`domimap/service.py`（T8）暴露 as_of；CLI `--as-of`、MCP kg_explore schema 加 `as_of`（integer epoch，可选）、UI `&as_of=`。验收（AC-F4-01 方向）：冻结 as_of 日期矩阵夹具（旧/未知/未来/有效/替代五态×三入口）；touch 后 fresh 查询不再把旧文档顶到最前（图平面 first_seen 按 sha join store.content_first_seen，修 lite_scan.py:135-140→graph.py:178 链路）。负例：非法日期串保持资格+unknown 标注（现状语义保留）。

### Task 10: F3 接线（F3）
范围：`domimap/context.py`（`trusted` 必填、去默认自信任；walk 限深或改 docstring；sha 持久化对比）；`domimap/service.py` 增 `trusted_context()`；注册根清单进工作区 meta；生效诊断 = 每次加载返回 `{loaded, changed, dropped, truncated}` 事件记录。验收（AC-F3-01/02 方向）：嵌套作用域（子目录 AGENTS.md 覆盖/合并规则写死并测试）；文件改变被检出；跨仓负例保持；"摄入语料中的 AGENTS.md 不升级为指令"从"靠没人调用"变成"调用方强制显式 trusted"。负例：非可信根、超预算、双向编辑。

### Task 11: 原义 R06 + F4-02 接线（R06/R05/F4-02）
范围：`domimap/batch.py`（build/update 尾部调 `record_baseline` + `scan_dependencies`，digests 来自 EvidenceStore.list_sources）；`domimap/knowledge.py:99-103`（attach_if_present 传 current_digests）、`:176-184`（amend 事务内 DELETE claim_bindings；绑定键改 claim 内容摘要或双键）；CLI `review list/confirm`；UI 复核区块（无 AI 可完成）。验收（AC-R06-01/02 原义）：一笔记两陈述仅一条依据变化→恰一条待复核、重复 update 不重复产生；确认绑定当前证据+范围；点击/重建不刷新（现状 :287-292 保持并加测试）；陈旧审定在检索面显式 `stale`。负例：claim idx 错位不再压制复核（amend 后旧 binding 清除）。

### Task 12: 知识层写入口（R05/R07）
范围：`domimap/__main__.py` 新增 `note submit|amend|withdraw|accept|history`、`kb-backup|kb-restore|kb-export|kb-import`；MCP `kg_note`（与 kg_feedback 同一 `--enable-write` 门控、同 schema 校验）；`domimap/knowledge.py:193-205`（withdraw/accept 零行命中→ConflictError）。验收（AC-R05-01）：M3 出口"保存→修订→审定→新会话再检索→依据变化复核"全 CLI 可演；并发/幂等沿 tests/test_m3_knowledge.py 扩到 CLI 层。负例：未知 note_id 撤回报错而非静默；kb-import 冲突预览 API（`preview_import` 返回 current/file/revs_ahead）。

### Task 13: impact 因果语义（R04）
范围：`domimap/graph.py:269-281`（边类型白名单 CAUSAL = {CALLS, CALLS_SQL, READS, WRITES, PUBLISHES, SUBSCRIBES, RPC, ROUTES_TO, HANDLES, MAPS_TO}；路径强度 = min(CONF_ORDER)）、`domimap/scenario.py:102`、`domimap/__main__.py:196`（打印 `← src --KIND(conf)--> dst` 修正错位）。验收（AC-R04-02 方向）：MENTIONS/BELONGS_TO 不再入影响面（新负例：doc 提及 t_order 不算被依赖）；最弱边语义测试；三入口 partial 一致（依赖 T8）。风险：现网影响面会变小——这是纠正"制造影响事实"，须在 CHANGELOG 明示行为变化。

## P2 任务卡

### Task 14: `domimap connect <claude|codex|zcode|dsh>`（F1-C1..C4）
范围：新 `domimap/clients.py` + `__main__.py connect/disconnect`；每客户端版本化原生配置模板（Claude `~/.claude.json` mcpServers 片段 / Codex TOML / ZCode `~/.zcode/mcp.json` / DSH `cordis.patch.yml`——以 docs/clients.md:9-12 的实测登记为准）、托管标记幂等增删、`doctor --clients` 生效诊断；同步修正 docs/clients.md:12 vs :14 的 DSH 身份矛盾（以最新实测为准并注明日期）。验收（AC-F1-C*-01/02）：每客户端"新会话发现→查询→读取→上下文生效"真实会话记录 + 幂等撤销 diff 为空。阻塞如实保留：Codex 账号锁定、DSH 模型 402 属外部条件，登记 blocked 不虚报。

### Task 15: 卫生批处理（§5 清单 1-10）
一次性小 PR 集合：计数/文案五处（ui.py:3-4,416、test_ui_workbench.py:25-27、__main__.py:24、production-readiness.md:39、roadmap.md:102 若 T1 未覆盖）；CHANGELOG 重复标题与 597→601；acceptance.json 排序+换行；context.py:13 docstring；.gitignore 加 `queries.db`/`queries.db-*`/`queries.key`；qexport/diagnose 输出前打印"含查询原文，勿发布"提示（仅当 keep_text 生效时含原文）；feedback.py:492-498 部分删除也要求（或自动快照）备份并对齐 AC-R06-04 文本；TWELVE_OF_TWELVE_RESULT.json 加 `"status":"diagnostic_only"` 顶层字段或改名；Actions 钉 SHA；`requires-python` 提到实测下限或补 CI 矩阵；三 DB 打 `PRAGMA user_version` 开检；doctor 增 DB 完整性检查；store.py 全流 sha（或并记 full_sha）与 GBK 定位符解码；scenario.py:33-43 改传 seeds。每项独立小测试，允许拆多次提交。

## 执行顺序与依赖

```
T1(裁决) → T2(MCP门控) → T3(manifest)     ← 先恢复记账诚实性（~1.5 天）
T4(捕获) → T5(身份) → T6(原子发布) → T7(整库恢复)   ← 地基链（~1 周）
T8(应用服务) → T9(as_of) / T11(R06原义) / T12(知识入口)   ← 入口接线（~1 周，T9/T11/T12 可并行）
T13(impact 语义) 随时可做（独立）
T14(四客户端) 在 T8 后
T15(卫生) 穿插任意间隙
```

每任务落地即按 workflow.md §5 重跑受影响案例证据（42 例 stale 的清偿随切片自然发生，不集中补账）。

## 自审（writing-plans Self-Review）

1. **规范覆盖**：2.1-2.5 五类漂移 → T1(2.2)/T2(2.5)/T3(2.4)/T4-T7(2.1)/T8-T13(2.3+§3 各行)；§5 卫生 → T15；四客户端 → T14。无遗漏项。§3 表中"Correctly implemented"各项无任务（保持现状即正确）。
2. **占位符扫描**：T1-T3 每步含完整代码/命令/预期；T4-T15 为任务卡——按技能 Scope Check 规则显式声明"开工时展开为独立计划"，非占位符伪装。
3. **类型一致性**：`visible_tools(enable_write)`/`Server(graph_path, enable_write=False)`/`serve(graph_path, enable_write=False)` 三处签名一致；`check_manifest_bounds(name, task)` 在 check_task 与 main() 两处调用一致；`agent_relay` 在 SOURCE_VALUES、T2 测试、T12 kg_note 门控三处一致；R15 案例号映射 03→01…07→05 全文一致。
