# m2-closeout：覆盖缺口可见（R02-02）/ 分路召回+家族去重（R04-01）/ MCP 容错（R08-03）

- R04-01：query 分路召回——Doc 路与其他路分开排序融合（文档不饥饿，Doc 候选存在时保底 2 席）；主候选按 file 家族去重（同文件 ≤2 席，解决真实回放发现的 seeds.json/README 榜首噪声）。
- R02-02：query 结果携带 coverage 摘要（scanned/skipped/未解析原因计数）；MCP/CLI 同步可见。
- R08-03：MCP 非法对象/入参/超大请求 → 有界结构化错误（不泄漏内部异常文本，修 D2 残留）；后续有效请求可用；stdout 仅协议。
