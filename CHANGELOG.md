# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式与语义化版本。

## [Unreleased]

### 漂移纠正二期（2026-10-26 全项目漂移审计 → docs/superpowers/plans/2026-10-26-drift-analysis-and-priorities.md，T1–T15）

- T1 spec-rehome-r15：R06 回归原义"依据变化→定位陈述→复核队列"（AC-R06-01/02）；检索反馈闭环五案例迁册为 R15「检索质量反馈与受控进化」（AC-R15-01..05，文本逐字不变、连续归位）。`check_specs.REQUIREMENTS` 显式需求集 21→22（精确相等守卫保留）；product.md/roadmap 同步；12 份历史任务 manifest 与守账测试改用新 ID；证据按新 case_id 真实重跑定稿。
- T2 mcp-write-gate：MCP 写工具 `kg_feedback` 改为 `domimap serve --enable-write` 显式启用——默认服务 `tools/list` 只公布 6 个只读工具，未启用时调用返回 `isError` + `write_disabled`；经 MCP 转达的判定以新来源 `agent_relay`（∈ SOURCE_VALUES、∉ AUTHORITATIVE_SOURCES）落库，不进命中率/覆盖率/诊断队列口径，响应附 `source` 字段；`schema.json` 增 `mcp_write_tools` 并有契约测试。行为变化：此前任何 MCP 客户端可写入权威 `user_feedback`；现在人工确认须经 UI/CLI。
- T3 manifest-bounds：`check_specs.check_manifest_bounds` 按 `kind` 约束任务 manifest 白名单——`slice` 不得列规范文件或其他任务 manifest，`spec-change` 不得含 `domimap/` 产品代码，`umbrella` 须写 `reason`；`--task` 与全量结构校验都执行。此前 14 份 manifest 共用同一份 79 文件全仓清单（含 requirements/acceptance.json），`--task` 范围检查形同虚设；现按各任务 .md「## 文件」节裁剪（c0 定为 spec-change，publish-openprep×2 定为 umbrella 并写理由，另 4 份去除并行兄弟 manifest 条目）。task-template.json 与 workflow.md §2 同步。
- T4 capture-unification（关闭 D10，R02/R03）：扫描器单次读取字节并经 `capture` 回调即时固化为证据（`capture_source(raw=)` 不再二次读盘；docx/pdf 经 BytesIO 同源抽取），`graph.build` 委托 `batch.build_many`——**普通 `domimap build <repo>` 现与 `--discover` 一样产出 store.db/不可变代/manifest**，`kg_explore` 尾部 ev_id 可 `kg_read`，`domimap update` 在单仓产物上可用（此前 exit 5）；捕获/读取失败进 coverage.skipped；服务命名策略写入 manifest.service_prefix，update 沿用（单仓节点 ID 不变）。617 tests OK。
- T5 source-identity（关闭 D11，R01）：同名来源仓标签自动去重（`name~<路径摘要6>`，仅冲突者），写入 manifest `label`，同 basename 两仓不再覆盖彼此 sources/manifest；每条扫描记录戳 `sid=label|rel`，图节点 meta 携带，`store.EvidenceResolver` 先按 sid 直达 ev_id、旧图（无 sid）才按唯一 rel 回退——MCP/UI 候选证据链路改用它；**行为变化：Route/SqlStmt/Page 节点 ID 带服务限定**（`route:<svc>:<METHOD> <path>`、`sql:<svc>:<iface>.<id>`、`page:<svc>:<url>`），跨仓同路由/同 iface.id 不再合并；新增 `domimap rebind <label> <path> -o DIR`（manifest 即持久化来源登记，重绑只改物理路径，sid/节点 ID 不变，内容未变则 update no-op）。622 tests OK。
- T6 atomic-publish（关闭 D12 与 D1 残留，R03）：graph.json/coverage.json/manifest.json 一律 `_atomic_write`（tmp→fsync→rename→目录 fsync），兼容副本字节等于 active 代；`_store_healthy` 校验 graph.json sha==active 代（缺失/截断/篡改→重发布，不再误报 no-op）；manifest 文件签名由 `[mtime_ns,size]` 改为内容 sha256（扫描期 capture 回调同源计算，`cp -p`/`touch -r` 的同尺寸改写可识别；旧 manifest 首次 update 自愈）。628 tests OK。
- T7 workspace-restore（R07，AC-R07-01/03）：新增 `domimap/workspace.py` 与 CLI `export-workspace WS DEST` / `restore-workspace ARCHIVE TARGET`——导出把证据库一致性快照（SQLite backup）、blobs/、gens/、graph.json、coverage.json、各来源 manifest、知识库（复用 kbackup v2）打成带逐文件 sha256 的 `workspace-manifest.json` 包，暂存整体 rename 发布、目标已存在拒绝；恢复要求目标不存在，逐成员校验路径不越界/非符号链接/sha 一致/无缺件，知识库经 `KnowledgeStore.restore` 校验，证据库 active 代可定位且 graph.json 字节等于该代后才 rename 发布，任一失败不留半成品（exit 4/5）。`EvidenceStore.active_generation` 代文件按本库旁 gens/ 回退定位（工作区移动/恢复不再依赖发布时绝对路径）。查询日志默认不随包（`--include-queries` 显式带上并标注）。636 tests OK。
- T8 app-service（product#6，AC-R04-02/AC-F2-01）：新增 `domimap/service.py` `AppService`——唯一的装配点（Graph/coverage/Searcher/知识挂接/seeds/证据解析）与默认参数源（`QUERY_DEFAULTS` top_k 6/expand True/budget 3800/min_cov 0.3；`DOC_SEARCH_DEFAULTS` 8/False/6000；`IMPACT_MAX_NODES` 200），CLI/MCP/UI 只做协议映射。消除的分叉：UI 此前 `expand=False`；`kg_doc_search` 此前绕过 run_query 且无 seeds、不记录观测——现经共享路径记录并新增 CLI `domimap doc`；impact 预算此前只在 MCP 执行——现三入口统一 `partial`（CLI 新增 `--max-nodes`，打印修正为 `src --KIND--> dst`，此前 dst/conf 错位）；UI `/api/search` 此前无异常处理（异常=无 HTTP 响应）——现 400/500 JSON 且不外泄内部文本；UI 此前不热重载——现 graph/knowledge/store 任一变化即重建装配（笔记保存后整体重建，不再累加 BM25 统计）；CLI query 此前不传 coverage。641 tests OK。
- T9 time-policy（F4，AC-F4-01；D7 的资格/入口侧关闭）：**行为变化**——`valid_until` 已过期与 `superseded_by` 文档默认不具资格（此前该门槛只在 as_of 分支执行，默认查询放行过期/被替代资料，与代码注释"默认排除"相悖）；`as_of` 三入口可达并同语义（CLI `query --as-of YYYY-MM-DD|epoch`、MCP `kg_explore.as_of` epoch 秒、UI `/api/search?as_of=`，统一 `service.parse_as_of`，非法值为有界错误：CLI exit 2 / MCP invalid params / UI 400）；时效可解释——文本输出每条候选附 `[time:… era=content|store|mtime]` 与 `[valid_until:…]`，UI 种子携带 `time_note/era_source/valid_until`；无正文日期的文档纪元改取内容首次收录时间（store 按内容 sha 取 min：复制/touch 不再制造新鲜度，era_source=store），front-matter 元数据不再污染正文纪元。646 tests OK。
- T10 trusted-context（F3，AC-F3-01）：`context.load_context(root, trusted, budget, scope)` 不再默认信任传入根（无 trusted → PermissionError），规则文件经链接者跳过；嵌套作用域——同根多层 AGENTS.md/SOUL.md 全部列出（各带 sha256/size），只有 `scope` 向上最近的一层 `effective`，不拼接；超预算显式 `truncated+dropped`（生效条目优先保留），返回 `text`（生效条目带来源头）。工作区登记：`EvidenceStore.register_trusted_root/trusted_roots/remove_trusted_root`（store.db meta）；`AppService.trusted_context(scope, budget)` 汇合各可信根、按 `context_sha:` 记录做变更检测（首次全部为新，之后只报变化）。入口：CLI `domimap trust add|list|remove`、`domimap context [--scope]`；MCP 新增只读工具 `kg_context`（默认 7 只读 + 门控写 1；schema 校验新增 boolean 类型）。扫描摄入的 AGENTS.md 永不进入上下文（有测试）。653 tests OK。
- T11 review-loop（R06 原义 AC-R06-01/02 + F4-02）：此前 `record_baseline/scan_dependencies/confirm_review` 零生产调用、`attach_if_present` 从不传 digests（真实工作区永不产生待复核项）。现在 `batch.refresh_reviews` 在每次发布新代后运行：基线=陈述引用的 ev_id 自身版本（`EvidenceStore.review_digests().cited`，只补缺不推进），当前=同来源最新版本（`.current`），不同即入 `review_pending`（主键去重，重复扫描不重复待办；`new_evkey` 列记录可绑定的新证据 ID，旧库原地补列、旧 v2 归档兼容恢复）。检索面：`attach_if_present` 传 current digests，`_claim_stale`=在队列中或已绑定版本≠当前（点击/重建不清除），文本 `[stale:N 条陈述待复核]`、UI 种子 `stale`。确认：`AppService.confirm_review(note, idx)` 把引用换成最新 ev_id 并绑定版本；CLI `domimap recheck list|confirm`；UI `GET /api/recheck`。`amend` 替换 claims 时清理 `claim_bindings/review_pending`（此前 idx 错位可压制复核）。658 tests OK。

### 偏离纠正（drift audit 2026-10-26，C0–C7 已完成）

- 偏离审查（out/drift-audit-2026-10-26/，16 项可复现探针）发现十项实质偏离（F01–F10）；纠正任务 C0–C7 已全部完成：C1 安全恢复（先校验后触碰/占用拒绝/安全副本）与删除派生清理+裁剪保护；C2 请求身份排除耗时、密钥并发唯一赢家、版本含知识代际与词表指纹、记录延迟上界；C3 反馈全 payload 幂等、同来源显式修订（expected_revision）、AI 不改变人工样本选用、replay 不污染用户口径、分来源命中率；C4 簇键含范围版本、partial 入队、再裁决移出、当前重测与历史复现分离、召回池实证、AI 状态机（原子额度/并发单调用/非法输出 invalid_response/簇级冷却/unavailable 不占额度）；C5 精确节点评分（同文件错误节点=miss、旧子串格式拒绝）、冻结 manifest、activated 完整 lineage 门槛、追溯链限定；C6 MCP kg_feedback 工具+CLI qsnapshot/qrestore/qdelete+UI /api/event；C7 旧样例独立裁决（fastjson gold 判无效、无实词 gold 如实排除）与冻结样本集 v3 重证——目标名次 15→4、5→1、零回归、回滚等价，新启用 imp:d914a167c7a25b8401fe（旧 imp:ccf1ee268b695abbf2cd 失效留档）。597 tests OK；make release-check 仍按原规范拒绝（M0 implementing、四竞品比较未执行）。

### 已实现

### 已实现（原型演进，其中闭环相关条目按上段纠正中范围理解）

- 闭环追溯与改进启用记录（retrieval-evolution-replay，2026-10-26）：`queries.db` 新增 improvements 表——启用（activated）必须有回放依据（三 run 样本集一致且 candidate 对 baseline 判定 improved，否则拒绝登记）；`domimap evolution` 输出簇→用户事件→反馈修订→诊断（含 rank 证据）→回放 run 链→启用决定的完整追溯视图（--record-improvement 登记 activated/rejected/rolled_back）；问题簇积压按未诊断优先+影响面排序。真实数据收口：pilot 启用决定 imp:ccf1ee268b695abbf2cd 已登记，追溯链工件 out/dev-ws/evolution-trace.json（从原始事件 qe:41b0798e… 到 rank_15 诊断、9 个回放 run 与启用决定全程可读）。

- 首次真实「查询—反馈—诊断—修复—回放—回滚」闭环（retrieval-evolution-pilot，2026-10-26）：真实企业工作区（out/dev-ws）查询「商品 审核状态 流转」经反馈与诊断定位——含原始实词的《商品主数据融合项目设计文档》排第 15，top6 被 seeds 扩展英文词匹配的 generic 节点占据。候选 1（仅名称加成限定）真实回放失败并回滚留档；候选 2（名称精确加成限定于原始查询标识符 + 扩展词计分降权 EXPANSION_TOKEN_WEIGHT=0.35，独立任务 retrieval-identifier-boost-scope）回放 5/5：目标 1 名次 15→4、目标 2 名次 5→1、保持者 rank1 与负例零回归，回滚演练与基线逐样本一致后启用。新回放引擎 `domimap replay`：冻结样本集（sha 校验，改样本即不可比）、trigger=replay 不污染用户统计、expect=refused/expected=证据子串判定、基线/候选/回放三轮比较（regressions/improvements/verdict）。全程 ReplayRun 留档，事件/反馈/诊断/回放可追溯。

- AI 诊断与问题簇（retrieval-diagnosis，2026-10-26）：miss/失败/异常的用户事件按查询摘要归并问题簇（正确拒答与 disputed 不入队）；确定性规则预检——期望证据解析（节点/ev 反解/名称路径）、诊断性重跑（top_k=50、确定性核心、trigger=diagnostic+parent 关联不污染用户统计）区分排序差距（rank_N）/召回差距（not_in_top_50）/已呈现被标 miss/范围过滤；拒答原因映射假设；期望不在图时"来源未覆盖"与"期望写错"并列 unruled 并进 unknowns。结构化诊断包（domimap.diag.v1）可 `--out` 导出给 coding agent；可选模型分析复用 anthropic 协议客户端——每簇一次、同输入+版本复用、失败冷却 300s、输入 8000 字符/输出 1500 token 上限、白名单字段解析（超界丢弃并记录）、DATA 段声明数据非指令；无 key → ai=unavailable 规则诊断不受影响。CLI `issues`/`diagnose`；UI「反馈与历史」新增只读问题簇区块（诊断执行走 CLI，避免 UI 触发模型费用）。

- 查询反馈与统计（retrieval-feedback，2026-10-26）：queries.db 追加 feedback 表——hit/partial/miss/not_applicable 相关性与 success/failure/correct_abstention/needs_clarification 任务结果提交（CLI `feedback`、UI 结果区反馈条与 POST /api/feedback），修订追加保留历史（superseded_by 链）、幂等键同内容去重异内容冲突；有效相关性=权威来源（user/human/dev_gold）最新修订，权威矛盾进 disputed 不计命中率，ai_suggestion 永不覆盖人源且单独统计。`history`/`qstats`/`qexport` 与 UI「反馈与历史」工作流：H/(H+P+M) 完整命中率（unknown 不算 miss、partial 不折算）、判定覆盖率、来源分列、正确拒答比例（仅 refused 且有权威反馈者）、user/非 user 触发分离（回放与开发评测不污染用户统计）、同 profile 去重（重复次数单列）；受控删除（全量删必须先出示 snapshot 备份）+ SQLite backup API 一致性快照与结构校验恢复；成功/失败样例导出（未保存原文者 replayable=false）。

- 查询可观测性（retrieval-observation，2026-10-26）：CLI/MCP/UI 三入口经同一记录服务把每次查询写入工作区 `queries.db`（独立于权威证据/知识库）——执行状态（ok/refused/error/cancelled）、结构化拒答原因码（identifier_absent/empty_query/generic_only/coverage_below_min/domain_filter_empty/no_strong_candidate，与拒答分支一一对应，不再从中文文案反推）、实际参数、有序候选、版本指纹、耗时。记录 fail-open（异常→`recording_failed`，查询排序/拒答/exit code 逐字不变）；隐私默认不存原文（HMAC 工作区密钥摘要，`DOMIMAP_KEEP_QUERIES=1` 才本地保留，`DOMIMAP_OBSERVE=0` 关闭）；幂等键同内容去重、异内容显式冲突不覆盖；重试/回放以 parent/trigger 关联不污染真实请求数；容量上限最旧先出。反馈闭环（retrieval-feedback-evolution 计划）的地基切片。

- 工作台改版（product-ui-workbench，2026-10-24）：`domimap ui` 由单框搜索页升级为工作流工作台——左列枚举当前全部 13 条工作流（7 条工作台直接运行：检索问答/需求定位卡/问题排查卡/影响面分析/领域地图/证据阅读/笔记沉淀；6 条终端命令：建图/增量更新/嵌入索引/LLM 草稿/人审导出/MCP 接入，附精确命令与复制按钮），中部节点链画布（运行时节点高亮推进），页眉注入图规模/证据库/笔记/嵌入索引状态。新增只读 API `/api/scenario`、`/api/impact`、`/api/domain`，`/api/read` 支持 `?sid=`，全部沿用回环 Host/Origin 校验与 Searcher 同源语义；页面改用纯 DOM API 渲染并加 CSP（`default-src 'none'`）；文案去营销化（无"智能/助手/大模型"用语）。同任务修复 `/api/read` 参数校验先于库存在性检查、查询参数双重 URL 解码两个继承问题。

- 工作台 50 轮界面优化（product-ui-workbench-opt50，2026-10-24）：视觉——8px 间距体系/分层配色/字体层级/卡片阴影/暗色模式(prefers-color-scheme)/画布点阵网格与右缘渐隐/目录单字方章/类型徽章分色/候选阶梯淡入/节点运行呼吸与连线流动动画（respect prefers-reduced-motion）/细滚动条/sticky 毛玻璃页眉/响应式断点；交互——键盘导航（↑↓/Enter/Esc///）、URL hash 路由、表单记忆与最近使用标记、目录过滤（联动隐藏空组）、画布缩放（+/−/100%，占位容器防裁切）与折叠开关、候选序号+Alt+数字 直开证据、证据徽标点击复制、结果一键复制与运行耗时徽章、会话查询历史、粘贴即搜、领域 datalist 建议、候选所属领域标签、知识候选人工/LLM 来源标识（API 附 conf/domain）、证据片段折叠、拒答态改信息条、页脚快捷键速查；无障碍（role/aria-label/aria-live/focus-visible）。每轮独立改进→重启→全新加载验证，里程碑截图评审两轮；终审修复：缩放/收起控件整合、证据徽标精简、renderSearch 重复代码块清除、coverage 显示语义错误当轮撤下。清单归档 out/verification/ui-workbench-opt50.json。
- 工作台 Playwright 全流程自测轮（同日）：修复证据链路映射断点——候选/`/api/read?node=` 经 rel 路径映射到 evidence 表真实 ev_id（点候选直读固化原文，含 Java/DDL/文档），候选携带可读 `ev` 字段；UI Searcher 与 CLI 同样挂接 knowledge.db 且笔记保存即时重挂可检索；页眉统计经 `/api/stats` 随保存刷新。13 条工作流（7 可运行 + 6 命令型）成功/失败/边界态逐条实测通过。

- 拒答原因诚实化（search-refusal-reason，同日）：Playwright 自测三次独立复现——`domimap search` 拒答分支（`cov < min_cov or not scored or not strong`）文案一律印"覆盖率 X% 不足 Y% 阈值"，域过滤筛空候选（覆盖率明明达标）时自相矛盾并误导排障方向。现按真实触发条件分化文案（覆盖率不足/域过滤后无候选（点名域值）/无强命中候选/仅通用词），`refused` 标志与拒答判定不变；UI 拒答前缀改"拒答："不再硬编码原因，GET 型工作流输入超 2000 字符前端诚实拦截（原为必然撞 HTTP 414 的开发者黑话报错）。

- 页眉统计随页面加载刷新（ui-stats-fresh-load，同日）："每次全新加载重测"第 2–4 轮复现——`domimap ui` 的 `/` 返回启动时一次性渲染的整页（stats 冻结快照），长驻服务里保存笔记/建嵌入索引后刷新页面看到的仍是启动时刻状态（笔记数不显示）。`/` 改为每请求现渲染，新加载页面即得实时统计；新增回归测试（保存后全新加载注入 STATS 即含新笔记数，无需客户端刷新）。

- note 保存服务端校验与运行面板交互加固（ui-note-validation，2026-10-25）：第三轮重测前置探测复现——`POST /api/note/save` 对缺失/纯空白 body 返回 200 并创建空笔记进检索池（UI 前端挡了、API 层没挡）。现空正文/claims 非数组一律 400 且计数不变（"空参不静默"契约）；运行面板输入控件 Enter 触发运行（isComposing 守卫防输入法误触、textarea Shift+Enter 保留换行）；finishRun 加 CUR 守卫，迟到的旧响应不再可能把切换后的新画布标成已运行（慢盘/隧道下的理论竞态窗口）。并发幂等语义（同 key 同文去重、异文 409）验证无回归。

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
- 机器可读 schema：`domimap schema` 输出节点/边/置信度/prov/工具/拒答门 JSON（`domimap/schema.json`），契约测试用真实构建反向校验零漂移（并据此修正文档中 READS/WRITES 边与 seed/vote prov 域）；README 增真实 UI 截图与 schema 章节。
- 分发就绪：版本 0.5.0、`domimap --version`、PyPI Trusted Publishing 工作流（`.github/workflows/pypi.yml`，tag 与 pyproject 版本校验）；`pip install pypdf python-docx` 缺失时 PDF/DOCX 契约测试自动跳过。

## [0.4.0] - 2026-10-16

原型版本。多仓 Java 扫描（Spring/MyBatis/Dubbo/RocketMQ/通用 MQ/JPA/跨端 + lite 方法级 CALLS）、中文混合检索（诚实拒答）、领域种子打标、查询索引磁盘缓存、CLI 与 MCP stdio 服务器（5 工具）、回放验收测试（夹具级）、pyproject 打包。

已知缺陷见 docs/known-defects.md；本版本不声明生产可用，未做四竞品比较。

## [0.3.0] - 2026-10-16

定名 domimap（原占位名废弃），清除业务数据与真实仓扫描产物。

## [0.2.0] - 2026-10-16

首个可执行落地包：7 synthesizer、多仓发现/合并/增量、MCP 热重载、治理 lite、16 golden 测试。
