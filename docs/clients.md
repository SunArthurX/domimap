# 四客户端接入调查（M0.4 基线）

日期：2026-10-16。本表登记**本机实测**的产品、版本与接口现状；未验证的不写"支持"。M4 案例验收前，任何一行都不得升级为"已接入"。

| 客户端 | 本机实测 | 版本证据 | 原生接口现状 | M0 结论 |
|---|---|---|---|---|
| Claude Code (F1-C1) | ✅ 已安装 | `claude --version` → 2.1.296（`~/.local/bin/claude`，配置 `~/.claude`） | MCP stdio 客户端（`~/.claude.json` 的 mcpServers）；M2 首条链路使用 | 可联调，M4 完整验收 |
| Codex (F1-C2) | ✅ 已安装 | `codex --version` → codex-cli 0.148.0（nvm node v24.15.0，配置 `~/.codex`） | 原生 MCP 支持待按其配置格式确认（M2 任务） | 可联调，M4 完整验收 |
| ZCode (F1-C3) | ✅ 宿主存在 | /Applications/ZCode.app → CFBundleShortVersionString 3.15.3（本开发会话即运行于其中；配置 `~/.zcode/`） | CLI 不在 PATH；`Resources/cli`、`Resources/mcp.json` 存在，接入方式在 M2 按 F1-C3 任务实际验证 | 产品已定位（3.15.3），接口待 M2 验证；不再是"未发现产品" |
| DSH Code Agent (F1-C4) | ✅ 产品已定位 | **@deepseek-ai/dsh（DSH Code Agent）v0.1.2-alpha.1**——`EXTERNAL_FAMILY_PATH`（monorepo，CLI bin `dsh`→apps/cli，web/host 双面）；`~/.dsh/` 为其数据目录（providers minimax/zai，会话 zstd） | CLI 未全局安装（node_modules/.bin 无 dsh）；本地经 `pnpm dsh`/tsx 可拉起。接入验证走 MCP 配置面（AC-F1-C4-02 配置接入 + 诊断） | M4 验证：cd deepseek-harness && pnpm dsh 拉起 + MCP 注册实测 |

修正记录：roadmap §5 曾写"ZCode/DSH 未唯一定位到本机可运行产品；本轮 PATH 未发现命令"。本次实测修正：ZCode 为本机桌面宿主 3.15.3；DSH 存在数据目录但程序本体未定位（维持 blocked）。结论以本文件实测为准，后续每次 F1 任务更新本表并注明日期。

## MCP SDK 选择（试验结论）

- 官方 Python SDK：PyPI `mcp`，实测最新 2.3.0（2026-10-16），`requires_python >= 3.10`。
- domimap 核心 Python 要求保持 `>=3.9`；**`mcp` 作为可选 extra**（`pip install domimap[mcp]`），仅 3.10+ 环境可装——不提升核心版本门槛。
- 当前 stdlib 自研 MCP stdio 服务器继续可用（零依赖路径保留）；SDK 用于客户端侧兼容试验（scripts/mcp_sdk_spike.py），M2 迁移服务端时再评估是否切换。
