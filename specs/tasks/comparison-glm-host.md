# comparison-glm-host：真实主轨宿主（GLM-5.3 × domimap MCP）

来源：用户 2026-10-17 明确授权"直接使用 zcode 的 key，模型 GLM-5.3"——主轨模型凭据解阻。

## 凭据纪律（安全边界，不可违反）

- requirement：F1-C3；acceptance：AC-F1-C3-01（ZCode 侧主轨链路证据）。

- key 来自用户本机的 ZCode 凭据库；**凭据库位置、加密方案与账号标识一律不进入仓库**。
  `load_api_key()` 只按序取：环境变量 `GLM_API_KEY`/`ANTHROPIC_API_KEY` → `DOMIMAP_KEY_HELPER`
  指向的本机未入库 helper 模块（默认 `~/work/dm-benchmark/zcode_key_helper.py`，实现
  `load_api_key()`）。helper 的解密细节在仓库外维护（2026-10-20 发布整理时迁出）。
- **只在进程内存使用；绝不写入任何文件/日志/工件/提交**；代码与产物中只出现脱敏引用。
- 端点：`https://open.bigmodel.cn/api/anthropic/v1/messages`，模型 `glm-5.3`（实测 200+usage）。

## 变更（精确 allowlist）

- `benchmarks/runners/glm_host.py`：load_api_key()（环境变量 / 本机 helper，内存使用）；McpBridge（spawn
  `python3 -m domimap serve -g`，initialize/tools/call）；GlmApiHost（HostAdapter 形态：
  open_session 每题新 MCP 会话；ask() 内部完整工具调用循环——kg_explore/kg_read 等
  anthropic tools 规范 → tool_use 执行 → tool_result 回填 → 终答；ledger 从 API usage
  累计）。
- `tests/test_glm_host.py`：**hermetic 契约**（注入假传输/假桥，无网络无费用）：
  工具循环执行、账本累计、终答提取、key 加载器永不写盘/日志脱敏。

## smoke（真实、有费、用户已授权；产物在 out/ 不入库）

5 题（四类+负例各 1）× domimap × glm-5.3 × pilot-clean r6 图；记录 synthetic:false、
model glm-5.3、全账本（tokens/tool_calls/secs）与完整转写。

## 回退

单提交回滚；凭据相关无任何落盘物。

## 边界

- 本 smoke 是链路证据（AC-F1-C3 侧），不是 480 题确认；不据此宣称任何指标。
- 竞品主轨（各自原生工作流接同一宿主）为后续任务。
