# context-root-protocol — RV04/RV05：可信上下文目标根选择与读取限制；MCP 业务错误一致性与协议版本协商

依据 out/agent-review-2026-10-27/review.md RV04（多根 AGENTS 同时 effective 并拼接）、RV05（业务失败 isError:false；协议版本固定 2024-11-05）。

## RV04：`trusted_context(root=...)`——单根默认（兼容）；多根未指定 → `ServiceError("ambiguous_root")` 列候选（结构化歧义）；只加载目标根（其他根内容不读）。读取前限制：`context.MAX_FILES=64`、`MAX_SCAN_SECONDS=2.0`（deadline 检查在 os.walk 每目录），超限 `limit_hit=True` 且 dropped 列出（显式截断）。MCP `kg_context` 增 `root` 参数；CLI `context --root`。

## RV05：`Server.call` 统一错误映射——InvalidParams/ServiceError/其他 → `isError:true` + 结构化 `{code, message, retryable}`（kg_note 业务错误上抛 ServiceError 而非内嵌 error-JSON 成功响应）；initialize 协商：请求版本在 `SUPPORTED_PROTOCOL_VERSIONS` 内回显，否则回 `LATEST_PROTOCOL_VERSION`（实测支持集如实声明为 2024-11-05，不以安装 SDK 冒充新版本支持）。

## 回归：tests/test_context_and_protocol.py 7 项（单根默认/多根歧义+根隔离/数量超限 dropped/MCP root 参数与歧义 isError/版本协商回显与回退/业务错误后有效请求恢复）。
