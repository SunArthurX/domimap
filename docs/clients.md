# 四客户端接入调查（M0.4 基线）

> 说明：本文是**开发期（2026-10）本机联调状态记录**，各行结论反映当时的实测环境（版本、账号、余额都会变化），不是对任何客户端产品的能力声明。接入方法（mcpServers 配置）长期有效，状态列请以自行实测为准。

日期：2026-10-16。本表登记**本机实测**的产品、版本与接口现状；未验证的不写"支持"。M4 案例验收前，任何一行都不得升级为"已接入"。

| 客户端 | 本机实测 | 版本证据 | 原生接口现状 | M0 结论 |
|---|---|---|---|---|
| Claude Code (F1-C1) | ✅ 已安装 | `claude --version` → 2.1.296（`~/.local/bin/claude`，配置 `~/.claude`） | MCP stdio 客户端（`~/.claude.json` 的 mcpServers）；M2 首条链路使用 | 可联调，M4 完整验收 |
| Codex (F1-C2) | ✅ 已安装 | codex-cli 0.148.0；domimap 已 `codex mcp add` 全局注册（enabled） | 会话传输通；**blocked：模型后端账号封锁**（穷举 9 模型名全被 ChatGPT 账号拒 + WebSocket refused） | **blocked**。所需最小输入：受支持模型名，或 `codex login --api-key` 切 API-key 认证 |
| ZCode (F1-C3) | ✅ 宿主存在 | ZCode.app 3.15.3；domimap 已注册 `~/.zcode/mcp.json`（标准 mcpServers） | 接口已验证、注册就绪 | **blocked**：需用户开新 ZCode 会话实测（发现→查询→读取）。所需最小输入：用户一次新会话操作记录 |
| DSH Code Agent (F1-C4) | ✅ 产品已定位 | @deepseek-ai/dsh v0.1.2-alpha.1（deepseek-harness）；domimap 已注册 cordis.patch.yml | 全链配置实测通过（RPC/会话/任务/读回） | **blocked**：模型 402 余额不足。所需最小输入：minimax-cn 充值，或任一有余额的 OpenAI 兼容 key+baseUrl |

修正记录：roadmap §5 曾写"ZCode/DSH 未唯一定位到本机可运行产品；本轮 PATH 未发现命令"。本次实测修正：ZCode 为本机桌面宿主 3.15.3；DSH 存在数据目录但程序本体未定位（维持 blocked）。结论以本文件实测为准，后续每次 F1 任务更新本表并注明日期。

## MCP SDK 选择（试验结论）

- 官方 Python SDK：PyPI `mcp`，实测最新 2.3.0（2026-10-16），`requires_python >= 3.10`。
- domimap 核心 Python 要求保持 `>=3.9`；**`mcp` 作为可选 extra**（`pip install domimap[mcp]`），仅 3.10+ 环境可装——不提升核心版本门槛。
- 当前 stdlib 自研 MCP stdio 服务器继续可用（零依赖路径保留）；SDK 用于客户端侧兼容试验（scripts/mcp_sdk_spike.py），M2 迁移服务端时再评估是否切换。
