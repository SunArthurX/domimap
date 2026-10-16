# m0-interface-survey：四客户端实测登记 + MCP SDK 兼容 spike

- 关联：R13（可追踪）；F1-C1/C2/C3/C4 的 M0 里程碑部分（查接口/登记，不完成 M4 案例）。
- 问题：roadmap 记"ZCode/DSH 未唯一定位"已过时，需以本机实测为准；MCP SDK 版本未选型。
- 实测结论（2026-10-16）：Claude Code 2.1.296 ✅；Codex 0.148.0 ✅；ZCode 3.15.3 ✅（桌面宿主，CLI 不在 PATH，接入方式 M2 验证）；DSH ⚠️ 仅 ~/.dsh 数据目录、程序未定位 → blocked（最小输入=产品名/安装来源+MCP 文档）。MCP SDK=mcp 2.3.0（py>=3.10，仅作 extra）。
- 交付：docs/clients.md（调查表+修正记录）、pyproject `mcp` extra、scripts/mcp_sdk_spike.py（SDK 客户端↔stdlib 服务端全链路）、scripts/refresh_evidence.py（证据定稿复用脚本）、tests/test_clients_doc.py（守护）。
- 正例：spike 在装 extra 的 venv 中 exit=0（log：out/verification/m0-mcp-spike.log）；make verify 含 4 项新守护测试全绿。
- 负例：调查表缺任一客户端/blocked 无最小输入/无 mcp extra → 测试失败。
- 回退：删除新增文件 + revert pyproject 两行；无数据迁移。
