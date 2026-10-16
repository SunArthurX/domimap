# m4-clients-c1：四客户端联调第一批（M4.1）

- **C1-01（verified）**：Claude Code 2.1.296 真实上下文任务会话（log m4-c1-01-session.log）：kg_explore→kg_read 多证据（ev:f413…/0e50…/2ae3…）→带出处结论，且发现真实一致性缺口（changePrice 未传 price_version + 先更新后发 MQ 的重试风险）——发现/查询/读取/上下文任务全链真实记录。
- **C1-02（verified）**：含空格路径接入（/tmp/dm space dir/）✓；重复 add 幂等（already exists 不重复建）✓；受管移除只删 domimap（7→6，其余保留）✓；重接恢复 Connected ✓（log m4-c1-02-managed.log）。
- **C2 Codex 0.148.0**：`codex mcp add` 全局注册成功（enabled，list 可见），会话创建/传输通；**模型后端账号级封锁**（gpt-6.1-sol/5.x 全部 "not supported with a ChatGPT account"）→ AC-F1-C2-01 blocked，最小输入=该账号受支持的模型名或改 API-key 认证。
- **C3 ZCode 3.15.3**：接口验证=~/.zcode/mcp.json 标准 mcpServers 格式（godot 先例）；domimap 已按原生接口幂等注册（备份 mcp.json.dm-backup）；AC-F1-C3-01 待用户开新 ZCode 会话实测（本会话无法嵌套拉起宿主）。
- **C4 DSH**：维持 blocked（~/.dsh 数据目录在、程序未定位；最小输入=产品名/安装来源+MCP 文档）。

## 收敛记录（2026-10-16）

- 上一会话 `refresh_evidence.py` 在 AC-F1-C1-02 处中止：其 evidence `command` 为不可执行的占位（`["claude","mcp","add/remove/list","..."]`，见 `_rerun-AC-F1-C1-02.log` 的 `error: unknown command 'add/remove/list'`），导致其后 13 例（F2/F3/F4-01/R05–R08/R12）指纹未刷新。
- 修复：按各例记录命令真实重跑（全部 exit 0，含 R12-01 真实任务回放 out/dev-corp-dev 预建图），回填指纹/工件哈希；R13-01 command 更新为 `--task specs/tasks/m4-clients-c1.json --base 3135267`；R14-02 负例/发布检查工件重生成（release-check 仍按预期失败：M4/M5 未完成）。
- 结果：`make verify` exit 0（117/117 测试），`--task` 范围检查通过，M0–M3 stage 检查全 PASS，25/44 verified。
- 遗留工具缺陷（下一 M4 切片处理）：AC-F1-C1-02 的 command 需替换为可重复执行的真实生命周期脚本（如 scripts/verify_m4_c1_02.sh，并补入任务 files），否则每次收尾 refresh 仍会在该处中止。
