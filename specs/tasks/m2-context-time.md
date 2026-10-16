# m2-context-time：F3 可信上下文加载 + F4 as_of 数据面（M2.3）

- 真实客户端链路已实测（out/verification/m2-claude-code-session.log：Claude Code 2.1.296 → MCP Connected → kg_explore 命中 → kg_read 固化片段带 sha256）；会话反馈：kg_explore 宜附证据 ID（记为 M2.4 改进项）。
- F3：`domimap/context.py`——只从**可信根**加载 AGENTS.md/SOUL.md（嵌套逐级、每条带 sha256/size、预算超限显式截断不静默）；语料目录的规则文件拒绝加载（不扩权限）。
- F4 数据面：store 的 first_seen 改为**按内容 sha 保留最早**（复制/重存不刷新）；publish 时把 first_seen 写入节点 meta；`Searcher.query(as_of=)` 资格先筛选（first_seen>as_of 不进候选）。
- 正例/负例见 tests/test_m2_context_time.py（先红）。

- 范围补充：scripts/check_specs.py —— 修复指纹不稳定性（tests/out* 生成物含时间戳导致证据写入即过期）。
