# product-llm-enrich：确定性解析之上的可选大模型增强层（单命令、可配置、草稿不入事实）

- 关联：R05（知识保存/审定/复用；AC-R05-02——"推断不混为事实"正是本任务的纪律）；R04（公共检索；AC-R04-01——增强笔记经文档路参与检索）。
- 来源：用户 2026-10-21 指示——"在 domimap 解析的基础上，学习 claude-obsidian 增加大模型解析，做成可配置的，一条命令触发；完成后用 zcode 的 glm-5.3 实测"。
- 立场（与 claude-obsidian 的对照）：它的核心是"宿主模型写知识 + 本地账本 grounding"；domimap 保持"确定性建图 + 证据纪律"不动摇，LLM 只作为**可选的语义增强层**：产出一律是 `inference` 型草稿主张（state=proposed），带 LLM 标注（conf=LLM / prov=knowledge:llm），人工审定接口不变（accept/confirm 才升级）。机器图的 EXTRACTED/INFERRED 语义零污染。

## 正例 / 负例

- 正例：`python3 -m domimap enrich -g out/idx/graph.json --limit 5` 一条命令完成——选 Doc 节点（meta.text 已在图内）→ 组装带出处的材料 → 调用可配置的 anthropic 协议端点（默认 bigmodel/glm-5.3，`DOMIMAP_LLM_ENDPOINT`/`DOMIMAP_LLM_MODEL`/flag 覆盖；key 取 `GLM_API_KEY`/`ANTHROPIC_API_KEY` 或 `DOMIMAP_LLM_KEY_HELPER` 模块）→ 解析为 summary/keywords/claims → 写入 knowledge.db（幂等键=节点+文本sha+模型）+ 审计文件 enrichment.json（prompt_sha/usage/原文摘要）。
- 正例：增强后的笔记经检索可见（AC-R04-01 文档路）：`query` 与 MCP `kg_explore` 自动挂接图旁 knowledge.db；LLM 笔记渲染为 `conf=LLM, prov=knowledge:llm`，人工笔记保持 `conf=HUMAN` 不变。
- 正例：幂等与增量——同图同模型重跑不产生新笔记、不重复调用（审计缓存命中）；`--force` 强制重做；`--dry-run` 不联网不落库。
- 负例：无 key/未配置时干净退出（exit 6），提示设置方式，绝不静默跳过或降级伪造结果。
- 负例：LLM 笔记的 claims 一律 type=inference、state=proposed，**永不** EXTRACTED/HUMAN；解析失败的条目记入审计错误项并继续，不写半截笔记；材料长度、条数、max_tokens 均有上限（R08 资源纪律）。
- 负例：不引入第三方依赖（stdlib urllib）；核心离线路径（build/query 无 LLM 配置）行为与现状逐字节一致。

## 实施（精确 allowlist）

1. `domimap/llm_enrich.py`（新）：`LlmClient`（anthropic messages 协议、有界重试、text 块拼接跳过 thinking）；prompt 组装（材料含路径与截断文本、系统提示禁止编造）；响应解析（宽容 JSON 提取+结构校验）；`enrich()` 编排（选目标/幂等缓存/写 knowledge/写 enrichment.json 审计）；配置解析（flag > env > 默认）。
2. `domimap/knowledge.py`：`LLM_NOTE_PREFIX` 常量 + `attach_if_present(searcher, graph_path)` 帮助函数（图旁 knowledge.db 存在才挂）。
3. `domimap/search.py`：`attach_knowledge` 对 LLM 笔记（body 前缀判定）标 `conf="LLM", prov="knowledge:llm"`，人工笔记语义不变。
4. `domimap/__main__.py`：`enrich` 子命令（--limit/--targets docs/--dry-run/--force/--model/--endpoint/--max-tokens/--cap）；`cmd_query` 挂接 attach_if_present。
5. `domimap/mcp.py`：`Server._reload` 挂接 attach_if_present（kg_explore 可见增强笔记）。
6. `tests/test_llm_enrich.py`：hermetic 契约（假传输注入，无网络无费用）覆盖上述全部正负例。
7. 文档：README（功能与配置表）、docs/knowledge-graph.md（LLM 增强层一节）、CHANGELOG。

## 验证与回退

- `python3 -B -m unittest tests.test_llm_enrich -v`；refresh_evidence 后 `make verify` 全绿（存量测试证明离线路径未变）。
- 真实 e2e（用户已授权 glm-5.3）：mini 夹具 `--limit 2` 实调 GLM-5.3（key 经本机 helper 注入内存），验证 200/usage、笔记落库、`query` 命中并带 LLM 标注；工件入 out/（不入库）。
- 回退：revert 本提交；knowledge.db 中 LLM 笔记可用现有 `withdraw`/`forget` 清理（正是复用现有治理通道的用意）。
