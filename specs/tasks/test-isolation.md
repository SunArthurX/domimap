# test-isolation — RV08：测试环境隔离与负载真实性

依据 out/agent-review-2026-10-27/review.md RV08。

## 修复：四个回环 HTTP 测试模块安装空 ProxyHandler（系统代理不再使 127.0.0.1 请求 502）；soak 混合负载写线程改用服务实际读取的 `out_shared/knowledge.db`（原旁路 `.soak.db` 冒充并发写），writer/publisher 连接在 finally 关闭。
