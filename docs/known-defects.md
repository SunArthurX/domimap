# 已知产品缺陷登记

日期：2026-10-16（M0 基线登记）。本文件是产品缺陷的权威清单；修复任务的验收以"登记条目关闭并有回归测试"为准。原型测试通过不等于这些缺陷不存在。

| ID | 缺陷 | 复现（夹具级） | 影响 | 计划修复 |
|---|---|---|---|---|
| D1 | 图丢失仍报 no-op：合并图 graph.json 被删/损坏后 `update` 只查仓 manifest，全 no-op，不重建图 | `python3 -B -m domimap build tests/fixtures/mini -o out` → `rm out/mini/graph.json` → `python3 -B -m domimap update -o out/mini`（报 no-op，图不恢复） | 检索面失效被误判为"无变更" | M1.4（AC-R03-02） |
| D2 | MCP 错误响应泄漏内部异常文本：`params` 为非对象类型时返回 `isError` 且 text 为原始异常串（`'str' object has no attribute 'get'`），未按 JSON-RPC 返回结构化 invalid_params。注：路线图登记的"令服务退出"在当前代码不复现（2026-10-16 实测坏请求后有效请求正常） | `printf '%s\n%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":"x"}' '{"jsonrpc":"2.0","id":2,"method":"initialize","params":{}}' \| python3 -B -m domimap serve -g <图>`（第一条响应泄漏异常文本） | 错误不可预期、可能泄漏内部细节 | M2（AC-R08-03） |
| D3 | 符号链接文件越界摄入：根内指向根外文件的 symlink 会被当普通文件读取，内容进入索引 | 在夹具目录 `ln -s /etc/hostname escape.txt` 后 build，hostname 内容入图 | 信任边界破坏（登记根外的内容被摄入） | M1（AC-R08-01） |
| D4 | 同名实体合并：Method/Class 节点按 service 级命名，跨类同名方法/类合并为一个节点（如 OrderController.changePrice 与 OrderPriceService.changePrice） | 查看 `out/mini/graph.json` 中 `mth:order-service.changePrice` 只有一个 | 影响面/调用链粒度失真 | M1.2（AC-R01-01） |
| D5 | 证据定位不足：节点仅含相对路径（部分含行号），无固化内容哈希/摘录；源文件修改后旧结果冒充当前 | build 后修改夹具源文件再查询 | 无法核验历史证据 | M1.3（AC-R02-01） |
| D6 | 无部署映射推定：RPC/领域关系基于词面，不区分版本/环境 | — | 关系可能不适用 | M1.1（AC-R01-01） |
| D7 | 时间维度缺失：无 as_of/时效/替代元数据，"最近"即默认最新 | — | 旧规范可能压过现行 | M2/M3（AC-F4-01/02） |

修复后请在对应行标注 closed-by 任务 ID 与回归测试名，并保留本行历史。
