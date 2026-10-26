# retrieval-observation — 查询可观测性（记录/结构化拒答原因/三入口关联 ID）

依据 out/plans/retrieval-feedback-evolution-plan.md P1 切片。日期：2026-10-26。

## 关联需求与案例

- 需求：R06（依赖失效与反馈闭环——本片建立其"查询反馈"半边的观测地基）、
  R01（如实呈现：执行状态与拒答原因不伪造）、R04（公共检索语义：三入口同源同序，
  记录不改变排序与拒答判定）、R13（spec-driven：本 task spec + 精确文件清单）、
  F2（人工 CLI/UI 搜索共用同一检索与记录语义）。
- 验收案例：**AC-R06-03**（本次在 specs/acceptance.json 正式登记，ID 已查重——
  registry 原有 AC-R06-01/02 偏知识依赖复核，不覆盖查询观测）。
- 保护（不修改其行为契约）：R02/R03/R05/R07/R08/F1/F3/F4/R14 及既有全部案例。

## 问题与用户结果

现状：任何一次查询（CLI `query` / MCP `kg_explore` / UI `/api/search`）执行后不留痕。
无法回答"哪些问题没找到、为什么、拒答原因是什么、当时返回了什么候选"。拒答原因
只有中文文案（search-refusal-reason 已分化文案，但机器侧仍需从文案反推），诊断与
统计（P2/P3）没有可靠输入。

本片后用户能得到：每次真实查询在本地 `queries.db` 留下一条事件（执行状态、结构化
拒答原因、实际参数、返回候选及顺序、版本指纹、耗时），三入口共享同一记录服务与
同一语义；查询结果本身（排序、拒答、exit code、输出结构）逐字不变。

## 边界（不做的事）

- 不改变检索排序、拒答判定、seeds/expanded 结构、CLI exit code、MCP 工具 schema、
  UI 既有 API 字段语义（只增不改）。
- 不做反馈提交、命中率统计、诊断、回放（P2–P5）。
- 不新增 Agent 运行时、网络调用、云服务；记录完全本地。
- kg_doc_search / scenario / impact 不是本片的"查询"面（它们是辅助工具）；留待后续
  切片按需登记。
- 不读取任何留出标注；不接触 benchmarks 正式协议。

## 数据契约（首个任务即冻结 schema）

存储：工作区图旁 `queries.db`（与 knowledge.db/store.db 同目录规则；该目录在摄入
范围之外——build --discover 只扫描含 pom/gradle/.git/package.json 的子目录）。
工作区密钥 `queries.key`（0600，随机 32 字节，首次生成）用于查询摘要 HMAC。

表（schema v1，`obs_schema=domimap.obs.v1`）：

```
query_events(
  event_id TEXT PRIMARY KEY,        -- "qe:"+sha256(idempotency_key)[:24]；无键则随机
  request_id TEXT NOT NULL,         -- 调用方请求分组
  parent_event_id TEXT,             -- 重试/回放关联（EV13：不污染真实请求数）
  entry TEXT NOT NULL,              -- cli | mcp | ui
  trigger_kind TEXT NOT NULL,       -- user | retry | replay | diagnostic
  created REAL NOT NULL,
  query_digest TEXT NOT NULL,       -- HMAC-SHA256(原始查询, 工作区密钥) hex——归并可用的
                                    --   脱敏指纹（普通哈希不保证隐私，不用）
  query_len INTEGER NOT NULL,
  query_has_cjk INTEGER NOT NULL,
  query_text TEXT,                  -- 默认 NULL；仅显式配置（keep_text）本地保留
  params_json TEXT NOT NULL,        -- 实际生效参数（top_k/domain/expand/budget/min_cov/
                                    --   seeds/semantic/rerank/embed/as_of）
  version_json TEXT NOT NULL,       -- domimap 版本/图指纹/节点数/idx schema；取不到=unknown
  status TEXT NOT NULL,             -- ok | refused | error | cancelled
  refusal_reason TEXT,              -- 结构化原因码（见下）；非拒答为 NULL
  cov REAL, min_cov REAL,           -- 拒答时的覆盖率事实（已计算处）；否则 NULL
  result_json TEXT NOT NULL,        -- 有序候选(id/kind/file，顺序即名次)、候选数、
                                    --   expanded_count、duration_ms、truncated、error 类名
                                    --   （error 时；P1 不记分值——rank 即诊断所需）
  idempotency_key TEXT UNIQUE,
  content_digest TEXT NOT NULL)     -- 内容摘要：同键重投一致性判定
idempotency_conflicts(key, content_digest, created, PRIMARY KEY(key, content_digest))
```

拒答原因码（`refusal_reason`，与 search.py 拒答分支一一对应，判定条件不变）：
`identifier_absent`（标识符守门，两处同语义）、`empty_query`、`generic_only`（仅通用词）、
`coverage_below_min`、`domain_filter_empty`（覆盖率达标但域过滤筛空）、`no_strong_candidate`。
未拒答事件 `refusal_reason=NULL`。**任何消费方不得从中文文案反推原因**（文案仅供人读）。

幂等与冲突：同 idempotency_key + 同 content_digest → 返回既有 event_id，status=
`duplicate`，不重复计数；同键不同内容 → 写 idempotency_conflicts，原事件不动，返回
status=`conflict` 与既有 event_id。无键请求（如 CLI 一次性调用）每次独立 event_id。

保留与容量：单工作区默认保留最近 20000 条（常量 MAX_EVENTS，写入后裁最旧）；当前
切片不做后台队列（有界单事务已足够，队列必要性留 P5 复核）。

隐私默认：`query_text` 默认 NULL（只存长度/是否 CJK/HMAC 摘要）。显式配置
`DOMIMAP_KEEP_QUERIES=1` 或调用方显式 keep_text=True 才本地保留原文。
`DOMIMAP_OBSERVE=0` 完全关闭记录（不建库不写）。导出工件与错误日志不含查询原文
（本片尚无导出；后续切片继承此约束）。

## 失败语义（不可破坏）

- 记录链路任何异常（库不可写/磁盘满/损坏）→ 返回 `{"event_id": null,
  "status": "recording_failed"}`，**查询结果照常返回**，不等待、不重试、不抛出。
  CLI 文本模式把该状态打到 stderr（stdout 契约不变）；UI 放进响应字段；MCP 放进
  附加行。记录失败绝不冒充成功（status 只在 INSERT 提交后才是 recorded）。
- 查询本身抛异常 → 先尽力记 status=error 事件（含异常类名），再原样上抛（CLI 既有
  traceback 行为不变；MCP 落 tool_failed；UI 落 500）。
- cancelled 为客户端中止保留语义（枚举登记、可写入）；三入口当前无显式中止路径，
  本片只保证枚举与写入通道存在。

## 设计选择

- **独立 SQLite 而非并入 store.db/knowledge.db**：高频观测数据与权威证据/知识分离
  （product.md 第 5 条：机器派生数据与权威数据分库）；重建索引/知识迁移不触碰观测
  记录。较简单方案"塞进 store.db 一张表"会让证据库的备份/恢复语义背上观测数据
  增长，且并发写热点耦合——不足取。
- **每次写入开短连接 + 进程内锁串行**：避免长驻 UI/MCP 进程持有跨测试的连接句柄；
  跨进程并发靠 SQLite 自身锁 + busy_timeout。后台队列/缓存留待证明必要（plan §5）。
- **HMAC 而非裸哈希**：plan §5 隐私要求——裸 sha256 可被彩虹/字典比对，工作区密钥
  化摘要把归并能力留在本地、把离线猜测挡在库外。
- **recorder 包装不进 Searcher**：search.py 只补结构化原因码（纯增量 dict 字段），
  记录服务在入口层包装（`observation.run_query()`），保证"测量工具与被测策略分离"
  （plan §4），且 Searcher 的全部既有调用方（benchmark/测试/scenario）零变化。

## 正例 / 负例 / 并发（Given/When/Then）

正例：
1. G mini 夹具图；W CLI/MCP/UI 同文本同参数查询；T 三者候选 id 顺序一致，各产生
   一条 entry 正确的事件（无跨入口合并，EV01）。
2. W 命中查询；T 事件 status=ok，result_json 含有序候选与 duration_ms>0，
   refusal_reason=NULL。
3. W 域过滤筛空/覆盖率不足/标识符缺席/仅通用词/无强命中/空查询 六路拒答；T 各自
   refusal_reason 码正确，status=refused，cov/min_cov 事实与计算处一致；CLI exit 3
   不变。
4. W 同 idempotency_key 同内容重投；T 第二次 status=duplicate 且事件数不变。

负例：
5. W 同 idempotency_key 不同内容；T status=conflict，conflict 表有记录，原事件
   字段未变。
6. W queries.db 不可写（路径被目录占用）；T 响应 status=recording_failed，
   查询结果/排序/拒答与无记录时逐字一致；CLI stdout 不含记录信息。
7. W 默认隐私配置；T query_text 为 NULL、digest 稳定（同查询同库）且跨工作区不同；
   keep_text 显式开启后原文仅在本地库。
8. W DOMIMAP_OBSERVE=0；T 不创建 queries.db，查询行为不变。

并发/中断：
9. W 多线程并发记录（8×20）；T 全部 160 条落库、event_id 唯一、无异常外泄。
10. W 记录中进程被杀（模拟：事务内异常）；T 库中无半行（单事务原子性）。

## 文件与有序任务

文件（本片 10 个）：
`domimap/observation.py`（新：ObservationStore/recorder/run_query）、
`domimap/search.py`（6 处拒答 return 增 refusal_reason/cov/min_cov 字段）、
`domimap/__main__.py`（cmd_query 接线：--json 增字段、文本模式 stderr 状态行）、
`domimap/mcp.py`（kg_explore 接线：结果尾附 query_id/recording 行）、
`domimap/ui.py`（/api/search 响应增 query_id/recording 字段）、
`tests/test_observation.py`（新）、`specs/acceptance.json` +
`specs/requirements.json` + `specs/progress.json`（AC-R06-03 登记）、
`CHANGELOG.md`、`docs/architecture.md`（§8 观测性段落）。

顺序：① search.py 原因码（测试先行暴露缺字段）→ ② observation.py + 单测 →
③ 三入口接线 + 三入口同序测试 → ④ registry/文档 → ⑤ 全量验证与证据。

## 验证

- `python3 -B -m unittest tests.test_observation -v`
- `python3 -B -m unittest tests.test_refusal_reason tests.test_negative_refusal
   tests.test_m2_query tests.test_mcp_desc tests.test_ui_workbench -v`（既有行为回归）
- `make verify`
- `python3 -B scripts/check_specs.py --task specs/tasks/retrieval-observation.json
   --base HEAD`（基线 HEAD=e90df78，实际存在的本地提交）
- 证据：`out/verification/AC-R06-03.json`（指纹/命令/工件哈希）。

## 文件登记说明

manifest `files` 除本片 10 文件外，还登记同工作区并行未提交任务
（product-ui-workbench / production-boundaries / search-refusal-reason /
ui-note-validation / ui-stats-fresh-load / analysis-interview / project-manual-motion /
project-question-visuals）的全部脏文件与 specs/progress.json——仅为全 diff 范围检查
（AC-R13-01）登记，不归本片成果，不回退、不改写。

## 回滚

删除 `domimap/observation.py`、`tests/test_observation.py`；revert `search.py`/
`__main__.py`/`mcp.py`/`ui.py` 本片差异；registry 三文件移除 AC-R06-03。
数据回滚：删除工作区 `queries.db`/`queries.key`（无其他迁移）。

## 遗留缺口（本片不做，后续切片）

- 反馈提交与修订（P2）、命中率统计口径（P2）、AI 诊断（P3）、回放与改进启用（P4/P5）。
- cancelled 的真实触发路径（UI 中止）留 UI 演进任务。
- 大规模保留策略（分页查询 API）在 P2 历史列表一并做。
