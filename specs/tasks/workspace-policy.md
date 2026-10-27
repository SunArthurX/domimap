# workspace-policy — RV04 剩余半项：工作区基线与仓级规则的显式优先序

日期：2026-10-28。依据 review.md RV04（"共同工作区规则与仓库规则应有明确优先级"）——前一轮 context-root-protocol 完成 root 选择/歧义/限制，分层未做。

## 修复：`register_trusted_root(label, path, level)`，level∈repo（默认，可多个）/workspace（**至多一个**，第二个不同路径拒绝——分层必须无歧义）；CLI `trust add LABEL PATH --workspace`，`trust list` 显示层级。`trusted_context` 分层解析：目标 repo 根 + workspace 基线（如有）都加载（各层独立限额/预算减半），**同类别（AGENTS/SOUL）仓级覆盖工作区**——被覆盖项 `effective:false, superseded_by:"repo:<label>"`，文本**不拼接**两份同类别规则（仓级未定义的类别由工作区补位）；响应携带 `precedence: ["workspace:<label>", "repo:<label>"]`。MCP kg_context 头部含 precedence 与逐项 level/superseded_by。无 workspace 时行为与 RV04 修复后完全一致（多 repo 根仍 ambiguous_root）。

## 迁移兼容：trusted_root 记录新增 level 键（缺省视为 repo，旧库无须迁移）。

## 回归（先红后绿）：tests/test_workspace_policy.py 5 项——workspace 唯一性（第二个拒绝）；同类别仓级覆盖（不拼接、superseded_by、precedence）；仓级缺类别由工作区补位；无 workspace 时歧义行为不变；MCP surface 携带 precedence。
