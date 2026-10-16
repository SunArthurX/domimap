# README 历史记录

以下保留整理前的规模报告与版本说明，不作为当前验收结果。当前入口见[项目说明](../../../README.md)。

## 历史规模报告

**历史规模报告（本次未复测）**：macOS M1 Max，45 仓、30,731 文件，约 33 秒生成 159,558 节点 / 337,615 边；全无变化检查约 0.6 秒。当前目录没有完整测量记录，不能由此推导结构正确率或变更更新性能。
工作区构建示例：`python3 -m domimap build <你的Java工作区> --discover -o out/ws-all`。目前任一仓变化后仍会扫描全部仓库，真正复用未变更仓的任务已列入 v0.5。

## 版本

- v0.4.0（2026-10-16）：增加 8 条夹具回放（旧混合口径 8/8；复核原始 Top-5 为 6/8）+ 修复查询单元与索引词表不对称（snake/camelCase 查询不再误拒答）+ 查询索引磁盘缓存（`<graph>.idx.json`，mtime/size/节点数指纹门控）+ lite 方法级 CALLS 边（INFERRED，同名方法仍有限制）+ pyproject.toml 本地打包与 `domimap` 命令入口；公开发布状态未在本次核查
- v0.3.0（2026-10-16）：定名 domimap，CLI `python3 -m domimap`，图 schema `domimap.lite.v1`
- v0.2.0：P0 完成 + P1 核心提前落地（16/16 golden 测试：5 synthesizer+跨仓 RPC+通用 MQ/JPA+增量 no-op+场景卡）
