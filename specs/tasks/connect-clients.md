# connect-clients — F1：四客户端原生配置的生成、幂等接入、受管撤销、诊断

日期：2026-10-26。依据 docs/superpowers/plans/2026-10-26-drift-analysis-and-priorities.md Task 14。

## 关联需求与案例

- F1-C1/C2/C3/C4（四客户端真实接入）。
- AC-F1-C*-02（版本化原生配置、幂等合并与受管撤销——本片提供可重复执行的动作；"在真实客户端中记录"仍需真实会话）。AC-F1-C*-01（新会话发现→查询→读取→上下文生效）本片不声称。

## 问题（漂移审计 §3 F1 行 / M4 矩阵）

四客户端均为一次性手工登记（`claude mcp add`、`codex mcp add`、手改 mcp.json、手改 cordis.patch.yml），无生成器、无版本化模板、无幂等撤销脚本；docs/capabilities.md 的 `domimap connect` 计划项长期未做；docs/clients.md 中 DSH 身份记录自相矛盾。

## 预期用户结果

- `clients.CLIENTS` 四条登记：产品、配置路径、格式、本机实测版本。`server_entry(graph, python, enable_write, repo_root)` 生成 `{command, args[-B -m domimap serve -g 图 (--enable-write)], env{PYTHONPATH}（源码检出时）}`。
- `connect(client, graph, …)`：dry-run 返回片段；条目相同 → unchanged（并补登记）；不存在 → added；存在且为本工具写入 → replaced；存在且非本工具写入 → ManagedConflict（--force 覆盖）；写前备份 `*.dm-backup-<ms>`；登记 `~/.domimap/connect.json`（client → config/entry_sha/template/written_at/backup/graph）。
- `disconnect(client)`：只删 domimap 条目；条目被手改且非 force → ManagedConflict；不存在 → removed=False。
- 格式：JSON（claude/zcode）原地改 `mcpServers.domimap` 保留其它键；TOML（codex）删旧表块后追加 `[mcp_servers.domimap]`/`.env`，3.11+ 写前 tomllib 验证；DSH YAML 在 `- insert:` 列表末尾追加/替换 `- id: mcp-domimap` 块，无 `- insert:` 时创建。
- `status(client)` / CLI `clients`：present/managed/graph_exists/command_exists/template/实测版本/`session_acceptance="未验收…"`。
- 退出码：未知客户端 2、图不存在 4、受管冲突 5。

## Given/When/Then

- 正例：预置含 other 服务与 theme 的 JSON → connect added（备份、其它键保留、args/env 正确）→ 再 connect unchanged（不重复备份）→ disconnect 只删 domimap；codex 预置 node_repl 表 → 追加 domimap 两表、tomllib 可解析、幂等文件不变、撤销后 node_repl.env 保留；dsh 预置 crm 行 → 追加 mcp-domimap 行、幂等不重复、撤销保留 crm；无 patch 文件 → 创建含 `- insert:`；`--enable-write` 透传；dry-run 四客户端均不落盘；CLI connect/clients/disconnect 往返且 `clients` 输出"未验收"。
- 负例：用户手写 domimap 条目 → connect ManagedConflict 且不覆盖，force 后 replaced；写入后被手改 → disconnect ManagedConflict，force 可删；未知客户端 ValueError/exit 2；图不存在 FileNotFoundError/exit 4。

## 设计选择

- 以"是否本工具写入且未被改动"（登记 sha）界定受管，而非在条目里塞标记键（避免破坏客户端 schema）。
- 不调用 `claude mcp add`/`codex mcp add` 子进程：直接写各客户端已实测的配置文件，离线、可测、可撤销；与官方 CLI 写出的结构一致。
- DSH 的 YAML 用行级块编辑并保留全部其它行/注释；不引入 yaml 依赖。

## 验证 / 回滚

见 manifest。tests/test_connect_clients 9 项（HOME 隔离到临时目录）。

## 遗留（如实）

- AC-F1-C1..C4-01/02 真实会话记录：Claude 可立即执行；Codex（账号模型封锁）、DSH（模型余额）为外部阻塞；ZCode 需用户开新会话。四案例保持 implementing/blocked，不因本片变 verified。
- `kg_context` 的客户端侧指引（会话开始调用）尚未写进各客户端的指令文件模板。
