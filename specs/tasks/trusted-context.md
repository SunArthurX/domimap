# trusted-context — F3：显式信任登记、嵌套裁决、变更检测、三入口可达

日期：2026-10-26。依据 docs/superpowers/plans/2026-10-26-drift-analysis-and-priorities.md Task 10。

## 关联需求与案例

- F3 可信 AGENTS/SOUL 定制；R08（普通文档不成为指令、不扩权限）。
- AC-F3-01（可信与普通摄入的规则文件、嵌套作用域 → 加载/修改/超预算 → 来源哈希独立生效，不串规则，不静默截断，不扩权限）。AC-F3-02（四客户端桥接生效）属 T14，本片不声称。

## 问题（漂移审计 §2.3/F3 行）

`context.load_context` 零生产调用；`trusted` 缺省为 `[root]`（自信任，安全靠调用方纪律）；docstring 称"一层嵌套"而实际全深度；无嵌套裁决、无变更检测、无入口。

## 预期用户结果

- 信任显式：`domimap trust add LABEL PATH -g 图` 登记可信根（realpath 持久化于 store.db meta）；`trust list/remove`。`load_context` 无 trusted 一律拒绝。
- 嵌套：所有层级规则文件列出（sha256/size），`scope`（根内相对目录，越界拒绝）向上最近一层 `effective`；`text` 只拼接生效条目并带来源头。
- 变更：`AppService.trusted_context()` 按 `context_sha:<label>/<path>` 比对，首次加载全部为新，之后只报变化；本次加载即视为已读。
- 预算：超限 `truncated=True` 且 `dropped` 列出（生效条目优先保留）。
- 入口：CLI `context [--scope]`、MCP `kg_context {scope?, include_text?}`（只读；默认 tools/list 7 只读 + 门控写 1）。
- 不升级：扫描摄入目录里的 AGENTS.md 不出现在可信上下文（仅作为 Doc 节点）。

## Given/When/Then

- 正例：根 AGENTS/SOUL + team/AGENTS → 无 scope 时根层生效、team 只列出；scope=team 时 team 层生效且 text 不含根规则；登记根后 service 首次 changed=全部、再次 []、改 team/AGENTS 后报告该路径且 scope=team 文本含新增；budget=40 → truncated 且 dropped 非空；MCP kg_context 列出工具且返回 AGENTS 文本、scope 越界 isError；CLI trust add/list/remove 与 context 输出。
- 负例：`load_context(root)` 无 trusted → PermissionError；scope="../outside" → PermissionError；fixtures/mini 放入 AGENTS.md 重建后不进上下文、未登记。

## 设计选择

- 登记放 store.db meta 而非独立 JSON：与工作区同生命周期，随 export-workspace 一起导出。
- scope 由调用方给（任务目录），默认根：不猜测 Agent 当前工作目录。

## 验证 / 回滚

见 manifest。653 tests OK（含 7 项新测试；两处旧测试改为显式 trusted）。

## 遗留

- AC-F3-02：Claude/Codex/ZCode/DSH 的原生桥接与生效记录（T14 `domimap connect` 时把 `kg_context` 调用写进客户端指引）。
