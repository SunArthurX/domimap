# product-ui-workbench — 工作台改造为 Dify/Coze 式工作流页面

## 背景

`domimap ui`（F2）目前是单框极简搜索页。用户要求：
1. 工作台做成 Dify/Coze 工作流形态：把当前支持的**全部工作流**枚举出来，
   以节点图画布呈现，并且能**直接通过工作流做事**（快速进入角色）；
2. 删除页面的 AI 味（营销词、助手口吻、装饰性元素），走专业工程控制台风。

## 范围（bounded slice）

只改 `domimap/ui.py`（页面 + 只读 API）与测试，不动 Searcher/Graph/store 语义。

### 工作流清单（与 CLI 能力一一对应，全部写出）

工作台可直接运行（只读，同一 Searcher/Graph 语义，无模型、仅回环）：

| # | 工作流 | API |
|---|--------|-----|
| 1 | 检索问答（词法召回→图扩展→排序→拒答判定→证据） | GET /api/search（既有，语义不变） |
| 2 | 需求定位卡（领域分类→词表扩展→分桶检索→定位卡） | GET /api/scenario?kind=req（新） |
| 3 | 问题排查卡（图+文档双路召回→疑点排序→排障卡） | GET /api/scenario?kind=trb（新） |
| 4 | 影响面分析（符号反查→反向依赖清单） | GET /api/impact（新） |
| 5 | 领域地图（领域×服务/表/主题/文档 + 跨域共享表） | GET /api/domain（新） |
| 6 | 证据阅读（图节点 / ev_id / sid → 固化片段） | GET /api/read（扩展 ?node= ?sid=） |
| 7 | 笔记沉淀（正文→knowledge.db，幂等） | POST /api/note/save（既有） |

终端命令工作流（写盘/长任务/需密钥，不进 UI 服务进程；页面展示精确命令 + 复制）：

| # | 工作流 | 命令 |
|---|--------|------|
| 8 | 工作区建图 | `domimap build <工作区> --discover -o out/idx` |
| 9 | 增量更新 | `domimap update -o out/idx` |
| 10 | 嵌入索引 | `domimap embed -g out/idx/graph.json` |
| 11 | LLM 草稿笔记（可选，conf=LLM，未配置退出码 6） | `domimap enrich -g out/idx/graph.json --dry-run` |
| 12 | 人审队列导出 | `domimap review -g out/idx/graph.json -o out/review` |
| 13 | MCP 客户端接入 | `domimap serve -g out/idx/graph.json` |

### 页面形态

- 左列：工作流目录（13 条，徽标区分「工作台运行 / 终端命令」）。
- 主区：选中工作流的节点链画布（HTML+SVG，静态布局，运行时节点高亮推进）。
- 运行面板：表单 → 运行 → 结构化结果（候选可点开证据）；命令型给复制按钮。
- 页眉：图名、节点/边数、证据库/笔记库状态（服务端注入）。

### 去 AI 味（R01 适用范围表述纪律）

- 无 emoji/渐变/助手口吻；不出现「智能/AI 助手/大模型加持」类营销词；
  LLM 能力如实标注「可选、conf=LLM、退出码 6」。
- 文案用工程动词：扫描、建图、检索、影响面、证据、笔记。

## 契约（不可破坏）

- AC-F2-01：/api/search 候选排序与其余两入口同源同序；响应在原字段上按需附加 `ev`
  （仅当该来源有固化证据），与 CLI 同样挂接图旁 knowledge.db（保存后即时重挂）。
- 证据映射：节点 file(rel) → 最新 ev_id（与 MCP kg_explore 的 rel 映射同粒度），
  给出的 ev ID 保证 /api/read 可读；无证据/无节点如实 404，不冒充内容。
- AC-R08-02：仅回环绑定；所有请求校验回环 Host/Origin/Referer；
  页面只用 `textContent`/DOM API，禁止 `innerHTML`；资料按数据渲染不执行脚本。
- 新增 API 均为只读 GET（或既有受保护 POST），空参/非法参 4xx JSON，不静默。
- 富 CSP：`default-src 'none'`，仅允许内联脚本/样式与同源 connect。

## 验证

- `python3 -B -m unittest tests.test_ui_workbench tests.test_m4_security tests.test_m2_shared -v`
- `make verify`
- Playwright 逐条自测 13 条工作流（成功/失败/边界态；证据链路用 --discover 真实 store.db）：
  候选带 ev 且点击直读固化片段、拒答/空输入/未知符号/非法 ev 如实呈现、
  笔记保存即时可检索、6 条命令正确且复制按钮生效、页眉统计随保存刷新。

## 回滚

单文件 revert `domimap/ui.py` + 删除新测试文件即可；无数据/格式迁移。
