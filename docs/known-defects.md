# 已知产品缺陷登记

日期：2026-10-16（M0 基线登记）。本文件是产品缺陷的权威清单；修复任务的验收以"登记条目关闭并有回归测试"为准。原型测试通过不等于这些缺陷不存在。

| ID | 缺陷 | 复现（夹具级） | 影响 | 计划修复 |
|---|---|---|---|---|
| ~~D1~~ 已关闭(m1-evidence-generations)：图丢失仍报 no-op——active 代校验+seeds 摘要门+空 manifest 报错（回归 tests.test_evidence_store） | `python3 -B -m domimap build tests/fixtures/mini -o out` → `rm out/mini/graph.json` → `python3 -B -m domimap update -o out/mini`（报 no-op，图不恢复） | 检索面失效被误判为"无变更" | **closed-by m1-identity-sources（回归：test_identity.test_symlink_escape_rejected_and_recorded）** |
| D2 | MCP 错误响应泄漏内部异常文本：`params` 为非对象类型时返回 `isError` 且 text 为原始异常串（`'str' object has no attribute 'get'`），未按 JSON-RPC 返回结构化 invalid_params。注：路线图登记的"令服务退出"在当前代码不复现（2026-10-16 实测坏请求后有效请求正常） | `printf '%s\n%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":"x"}' '{"jsonrpc":"2.0","id":2,"method":"initialize","params":{}}' \| python3 -B -m domimap serve -g <图>`（第一条响应泄漏异常文本） | 错误不可预期、可能泄漏内部细节 | M2（AC-R08-03） |
| D3 | 符号链接文件越界摄入：根内指向根外文件的 symlink 会被当普通文件读取，内容进入索引 | 在夹具目录 `ln -s /etc/hostname escape.txt` 后 build，hostname 内容入图 | 信任边界破坏（登记根外的内容被摄入） | **closed-by m1-identity-sources（回归：test_identity 越界拒绝）** |
| D4 | 同名实体合并：Method/Class 节点按 service 级命名，跨类同名方法/类合并为一个节点（如 OrderController.changePrice 与 OrderPriceService.changePrice） | 查看 `out/mini/graph.json` 中 `mth:order-service.changePrice` 只有一个 | 影响面/调用链粒度失真 | **closed-by m1-identity-sources（cls/mth/doc ID 限定；重载/字段别名精度仍属 M1.2）** |
| ~~D5~~ 已关闭(m1-evidence-generations)：证据定位不足——EvidenceStore 内容寻址 blob+locator+sha256，源改/删后旧 ID 仍读旧片段（回归同上） | build 后修改夹具源文件再查询 | 无法核验历史证据 | M1.3（AC-R02-01） |
| D6 | 无部署映射推定：RPC/领域关系基于词面，不区分版本/环境 | — | 关系可能不适用 | M1.1（AC-R01-01） |
| D7 | 时间维度缺失：无 as_of/时效/替代元数据，"最近"即默认最新 | — | 旧规范可能压过现行 | **AC-F4-01 侧 closed-by time-policy（2026-10-26）**：valid_until/superseded_by 资格门槛默认执行（此前只在 as_of 分支）；as_of 经 CLI `--as-of`/MCP `as_of`/UI `&as_of=` 三入口可达且同语义；time_note+era_source+valid_until 在文本与 UI 展示；无正文日期的文档纪元取内容首次收录（复制/touch 不刷新）；front-matter 不再污染正文纪元。回归 tests.test_time_policy。**AC-F4-02 侧 closed-by review-loop（2026-10-26）**：build/update 后按"引用版本=基线、来源最新=当前"扫描，依据已变的陈述入待复核队列并在检索面标 stale；`domimap recheck list|confirm`；amend 清理错位绑定。回归 tests.test_review_loop |

修复后请在对应行标注 closed-by 任务 ID 与回归测试名，并保留本行历史。

## 2026-10-24 重新核验

上表保留历史登记；关闭结论以实际反例为准。本次新增“再次摄入”和“协议顶层非对象”输入，证明早期反例覆盖不足。

| ID | 当前结论与影响 | 处理与回归 |
|---|---|---|
| D2 | 工具入参错误标成功、顶层 null/数组可使 stdio 退出 | 已关闭(production-boundaries)：有界 framing、对象/schema 校验及 isError；回归 tests.test_production_boundaries.TestProtocolBoundary |
| D5 | 旧 ID 经 sid 解析为新版本，跨来源同内容覆盖出处 | 已关闭(production-boundaries)：来源版本 ID、精确读取及完整性校验；回归 TestEvidenceIdentity / TestEvidenceAdapters；不声称修复所有格式定位 |
| D8 | 同连接线程间事务互相回滚，读操作混合多个修订 | 已关闭(production-boundaries)：共享连接互斥和读快照；回归 tests.test_knowledge_safety 并发写与跨连接读取 |
| D9 | 恢复覆盖已有库、验证不足、备份计数取自变化后的源 | 已关闭(production-boundaries)：v2 快照清单、暂存校验、不覆盖发布；回归 tests.test_knowledge_safety；整库含证据恢复已由 workspace-restore（2026-10-26）实施：`domimap export-workspace`/`restore-workspace`，回归 tests.test_workspace_restore |
| D10 | scan 与证据捕获分两次读源；普通单仓 build 绕过证据固化 | 已关闭(capture-unification, 2026-10-26)：扫描单次读字节经 capture 回调固化、docx/pdf 同源抽取；graph.build 委托 build_many，所有入口共用证据契约；捕获失败进 coverage；回归 tests.test_capture_unification（读盘计数/证据可读/update 命名不漂移/捕获失败入 coverage） |
| D11 | 来源身份依赖 label/basename，旧节点只带相对路径 | 已关闭(source-identity, 2026-10-26)：同名仓标签自动去重（`name~hash6`，仅冲突者）并写入 manifest；文件背书节点 meta 带 `sid=label\|rel`，`EvidenceResolver` 先按 sid 后按唯一 rel（兼容旧图）；route/sql/page 节点 ID 带服务限定；`domimap rebind` 显式重绑（manifest 即持久化登记，sid/节点 ID 不变）。回归 tests.test_source_identity。遗留：tbl:/dom: 仍为全局名（同名表/Topic 隔离属 M1.2）；source.py 的 SourceRegistry 为历史最小实装，生产身份由 manifest+store.sources 承担 |
| D12 | graph.json/coverage/manifest 不与 generation 一起原子发布 | 已关闭(atomic-publish, 2026-10-26)：三者一律 tmp+fsync+rename 原子落盘；graph.json 兼容副本字节等于 active 代，`_store_healthy` 校验其 sha（缺失/截断/篡改→重发布，补 D1 残留：graph.json 单独丢失不再误报 no-op）；manifest 文件签名改为内容 sha256（同尺寸+同 mtime 改写可识别，旧 [mtime,size] manifest 首次 update 自愈重建）。回归 tests.test_atomic_publish。遗留：active 代切换与兼容副本落盘仍是两步（中断窗口内二者都是完整快照，下次 update 自愈）；update 的 no-op 判定需重读全部文件哈希（≤2MiB/文件） |

## 2026-10-27 评审复验（out/agent-review-2026-10-27，RV01–RV08）

| RV | 复核结论 | 处理与回归 |
|---|---|---|
| RV01 构建中断混代/误报 no-op | 成立（两个中断反例复现） | 已修 generation-consistency：代绑定 sources 映射、EvidenceResolver 按图 sha 定位所属代解析、manifest 发布成功后落盘；回归 tests.test_generation_consistency |
| RV02 重载/跨仓同名表碰撞 | 成立 | 已修 entity-identity：方法签名 ID、表/列按声明方隔离、引用 AMBIGUOUS、顺序无关；**2026-10-28 topic-cluster 补齐遗留半项**：Topic 按消息集群（数据源家族）隔离 `topic:<cluster>:<name>`，同集群同名连接（共享依据显式），跨集群同名独立无共享边；回归 tests.test_entity_identity::TestTopicClusterIdentity |
| RV03 审定无版本约束/审计 | 成立（旧 accept 批准新内容复现） | 已修 adjudication-contract：expected_revision+statement 绑定、review_events 审计、MCP 审定须 DOMIMAP_MCP_ADJUDICATE；回归 tests.test_adjudication_contract |
| RV04 上下文跨根串用 | 成立（两根 AGENTS 同时 effective 拼接） | 已修 context-root-protocol：root 选择/ambiguous_root/文件数与时限；**2026-10-28 workspace-policy 补齐分层**：workspace 基线（至多一个）+ 仓级显式优先序（同类别仓级覆盖，superseded_by 不拼接，precedence 数组）；回归 tests.test_workspace_policy |
| RV05 业务错误 isError:false | 成立（kg_note 冲突返回成功） | 已修：call() 统一结构化错误映射；initialize 版本协商；回归同上 |
| RV06 证据刷新/过度认定 | 成立（三例） | 已修 evidence-honesty：客户端会话不刷指纹改降级；AC-R10-02/R12-02/F1-C1-01/02 如实退回 implementing |
| RV07 发布未绑门槛 | 成立 | 已修 release-gate：pypi 增 verify+release-gate 作业（当前必然失败=正确），publish 核对工件哈希 |
| RV08 测试隔离 | 成立（代理 502；soak 旁路写） | 已修 test-isolation：ProxyHandler({})；soak 写真实 knowledge.db |
