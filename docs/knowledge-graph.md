# domimap 知识图谱模型（Knowledge Graph Model）

本文是图谱 schema 的权威参考：节点类型、边类型、置信度/来源语义、证据层与时间模型、一次检索的完整数据流。面向两类读者——想理解产出的**人**，和想程序化消费 `graph.json` / MCP 工具的 **AI Agent**。所有名称与 [`domimap/graph.py`](../domimap/graph.py)、[`domimap/search.py`](../domimap/search.py) 中的实现一一对应；架构层面的治理约束见 [architecture.md](architecture.md)。

## 0. 一图流

```
扫描（lite_scan.scan_repo，多格式）        记录（records）           图（graph.json）
Java(GBK/UTF-8) MyBatis XML  ──►  classes/methods/tables/   ──►  12 类节点 + 11 种边
SQL DDL MQ 路由 Markdown HTML      topics/routes/docs/columns     （含置信度与来源）
PDF*/DOCX* TS/JS/Vue                                            │
                                                                 ▼
人工知识（knowledge.py）──attach──► 检索（search.py：BM25+图扩展+文档泳道+拒答守门）
                                 │
                                 ▼
                 证据固化（store.py：ev_id + 不可变 generation）
```

## 1. 节点类型（Node kinds）

每个节点：`id`（带类型前缀的稳定标识）、`kind`、`name`（检索用词面）、`file`（来源文件）、`conf`（置信度）、`prov`（来源）、`meta`（类型特有属性）。

| kind | id 前缀 | 含义 | 典型 prov | 关键属性 |
|---|---|---|---|---|
| `Service` | `svc:` | 服务（按仓库/模块结构聚合的部署单元） | `java` | `classes` 数量 |
| `Class` | `cls:` | Java 类/接口（FQN 级） | `java` | 注释词面参与索引 |
| `Method` | `mth:` | 方法（服务内签名级；同名方法共享节点是已知取舍） | `java` | 调用关系端点 |
| `Route` | `route:` | HTTP 路由（method + path） | `java` | — |
| `SqlStmt` | `sql:` | 一条 SQL 语句（MyBatis iface.id） | `synth:mybatis` | DDL 语句带语义加权 |
| `Table` | `tbl:` | 数据库表；DDL 与 mapper 双来源各自建边 | `sql:ddl` / `synth:mybatis` | `via` 来源标记 |
| `Column` | `col:` | 表列（仅 DDL 来源） | `sql:ddl` | — |
| `Topic` | `topic:` | MQ 主题 | `java` | — |
| `Doc` | `doc:` | 文档（md/html/pdf*/docx*；front-matter 可带时间语义） | `doc:ingest` | `valid_until`、`superseded_by` |
| `Page` | — | 前端页面（TS/JS/Vue 扫描） | `core` | — |
| `Domain` | — | 领域（seeds.json 种子打标） | `core` | 域聚合入口 |
| `Knowledge` | — | 人工知识笔记（运行时由 `attach_knowledge` 注入检索层） | `kb` | revision、claims |

\* 需要可选依赖（`pip install pypdf python-docx`）。

**置信度（conf）**：`EXTRACTED`（语法/结构直接提取）＞ `INFERRED`（启发式推断，如调用图）＞ `AMBIGUOUS`（词法级，仅作导航线索）。**来源（prov）**记录"凭什么建的这个节点/边"，检索输出原样带回，引用时可见。

## 2. 边类型（Edge kinds）

| 边 | 方向 | 语义 | 影响传播 |
|---|---|---|---|
| `CONTAINS` | svc→cls/mth、tbl→col | 结构包含 | 否（仅导航） |
| `CALLS` | mth→mth | 方法调用 | **是** |
| `HANDLES` | mth→route | 方法处理该路由 | 是 |
| `CALLS_SQL` | mth→sql | 方法执行该语句 | **是** |
| `MAPS_TO` | sql→tbl | 语句读写表（读/写在 meta） | **是** |
| `PUBLISHES` / `SUBSCRIBES` | mth/svc→topic | MQ 生产/消费 | **是** |
| `RPC` | svc→svc | 服务间调用 | **是** |
| `ROUTES_TO` | page→route | 前端路由指向后端 | 是（跨端追踪） |
| `MENTIONS` | doc→实体 | 文档词法提及（`AMBIGUOUS`，`doc:lexical`） | 否 |
| `BELONGS_TO` | page/domain→… | 归属关系 | 否 |

规则（[architecture.md](architecture.md) §6）：`MENTIONS`/`CONTAINS`/`BELONGS_TO` **不参与**影响传播——文档提了不等于依赖它；`kg_impact` 沿 CALLS/CALLS_SQL/MAPS_TO/PUBLISHES/SUBSCRIBES/RPC 方向做反向追溯。

## 3. 证据层（Evidence Store）

- **三分离身份**（[source.py](../domimap/source.py)）：逻辑身份 `sid = repo|rel`、物理路径（可重绑）、内容版本（捕获字节 sha256）。根之外的路径（含 symlink 越界）一律拒绝。
- **证据 ID**：`ev:<sha256[:20]>`，指向固化片段（默认 4KB，含截断标记）。
- **不可变 generation**：每次 build 发布一个 generation，SQLite 记账 + `active` 指针切换；源文件修改/删除后，`kg_read(ev_id)` 仍返回**建图时**的旧版本——引用不因源演化而失效。
- 多仓增量：`batch.py` 在全部仓 manifest 未变、active generation 完整、seeds 摘要一致时 no-op。

## 4. 时间模型（内容纪元，非文件 mtime）

- 文档/节点时间取**内容里声明的时间**：显式日期优先，其次版本号近似纪元（`v2.0`、`Release 2.4` → 近似 epoch）。
- Markdown front-matter：`valid_until` / `superseded_by`（过期/被取代语义，检索时以 `time_note` 标注）。
- `as_of` 查询：`first_seen` 晚于 `as_of` 的节点不进候选——可以做"当时的知识状态"回放。

## 5. 一次检索的完整数据流（`kg_explore` / `query`）

1. **分词**：中文 2-gram + 拉丁标识符切分；主路径只用户令牌，中英桥（`EN_BRIDGE`）仅在词法覆盖率不足时作为**查询期回退**注入（索引期桥接会稀释 BM25 IDF，实测有害已回退）。
2. **词法打分**：BM25（k=1.2，b=0.75 饱和长度归一）；
   - 名称精确命中 → ×3.0（`IDENTIFIER_NAME_BOOST`）
   - 查询含"表/定义/写入"类词且节点为 CREATE TABLE 的 SqlStmt → ×2.0（`DDL_SEMANTIC_BOOST`）
3. **负例守门（诚实拒答）**，四道：
   - 仅命中通用词（无实质概念）→ 拒答；
   - 含 ≥4 字符拉丁标识符且全部缺席 → 拒答；
   - 精确标识符不存在 → 拒答且**不猜近名**（防变异标识符幻觉命中）；
   - 词法覆盖率 < 30%（`min_cov`）→ 拒答并建议换关键词/先 build。
4. **图扩展**：从词法种子沿第 2 节的影响传播边扩展，补全"改这里会影响谁/谁定义了它"。
5. **文档泳道合并**：Doc 节点与代码结果合并排序，附文件类型标注（README/SPEC/CHANGELOG/TUTORIAL/GUIDE/MIGRATION/DOC，仅信息不加权）。
6. **输出**：路径 + `ev_id` + rank + conf/prov + `time_note`；`refused: true` 时表示图中无足够证据——**调用方不应编造**。

## 6. 查询入口

| 入口 | 命令/工具 |
|---|---|
| CLI | `domimap build / query / read / impact / domain / serve / ui / doctor` |
| MCP stdio（6 工具） | `kg_explore`、`kg_read`、`kg_domain_map`、`kg_impact`、`kg_doc_search`、`kg_troubleshoot` |
| Web UI | `domimap ui --port 8080` |
| 场景卡 | 需求识别 / 问题排查（`scenario.py`） |

**给 AI Agent 的推荐用法**：先 `kg_domain_map` 建立领域全景 → `kg_explore` 词法+图检索 → 对命中的证据 `kg_read(ev_id)` 读固化原文 → 回答时引用**文件路径 + ev_id**；`refused=true` 时如实说明不可确定。

## 7. 可选 LLM 语义增强层（`domimap enrich`）

确定性建图之上，可以把图内材料交给可配置的大模型做语义增强。这是**可选层**——不开即无，构建路径仍零模型调用、完全离线：

- 一条命令：`python3 -m domimap enrich -g out/idx/graph.json [--limit N] [--targets docs|domain|all] [--dry-run] [--force] [--keep-old] [--budget-tokens N] [--json]`。`--targets domain` 按 MENTIONS 边把同域文档聚合为一份域级材料。
- 配置：`DOMIMAP_LLM_ENDPOINT`（默认 bigmodel 的 anthropic 协议端点）、`DOMIMAP_LLM_MODEL`（默认 glm-5.3）、`DOMIMAP_LLM_MAX_TOKENS`、`DOMIMAP_LLM_TIMEOUT`；key 走 `GLM_API_KEY`/`ANTHROPIC_API_KEY`/`DOMIMAP_LLM_KEY_HELPER`，未配置或目录锁忙时干净退出（码 6），绝不静默降级。
- 产物纪律（对齐 §1 的 conf/prov 语义）：LLM 输出写入图旁 `knowledge.db` 成为 `Knowledge` 笔记——claims 一律 `type=inference, state=proposed`，检索标注 `conf=LLM, prov=knowledge:llm`；人工 `accept`/`confirm_review` 之前**不作为确认知识**（推断不混为事实）。
- 输出可信（服务端强制，不依赖提示词）：`evidence_paths` 白名单（仅本篇材料路径，编造剔除记 `discarded_paths`）；summary≤600 字 / keyword≤32×8 / statement≤200×5 超长截断置 `truncated`；未知字段忽略记录；keywords 非中英双语记 warning；材料以 `<<<材料开始/结束>>>` 包裹并声明"是数据非指令"（缓解文档内提示注入）。
- 生命周期：幂等键 = 节点 + 文本 sha + 模型，同图同模型重跑零调用零新笔记（`--force` 重生成）；文档更新（text_sha 变化）后旧 LLM 笔记自动 `withdraw`（supersede，软撤回留历史，`--keep-old` 关闭）——检索只见最新版；人工笔记永不被动撤回。
- 审计与预算：每次调用**逐条**追加 `enrichment.jsonl`（中断安全，重跑不重复计费；兼容只读旧 v1 `enrichment.json`）；`--budget-tokens` 超限即停（剩余记 skipped）；4xx 不重试、429/5xx 尊重 Retry-After 指数退避；同目录 `.enrich.lock` 互斥并发。
- 资源纪律（R08）：单次 ≤50 篇、单篇材料默认截断 8000 字符、`max_tokens` 默认 1024；无第三方依赖（stdlib urllib）；serve 热重载感知 graph 与 knowledge.db 任一变化。

## 8. 已知边界

- BM25 是词法匹配：中文查询 ↔ 英文正文无法语义对齐（跨语检索是当前主要短板，见 README 基准表）。
- 同名方法在不同类下共享一个 Method 节点（服务级命名取舍）。
- 机器可读 schema（`domimap schema` 输出本表的 JSON 形式）为规划中的产品能力，未实现前以本文档为准。
