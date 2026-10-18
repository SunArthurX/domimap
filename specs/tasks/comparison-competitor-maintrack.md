# comparison-competitor-maintrack：四竞品主轨注册与五系统对比（测试计划 §四 主轨）

来源：主轨全量首测（domimap 22/27+4/4）后的下一项；计划 §四"五系统使用相同宿主/模型/
提示/预算，每次只启用一个被测产品，使用各自原生工作流"。

## 变更（精确 allowlist）

- `benchmarks/runners/competitor_host.py`：
  - 宿主循环工具提供者化（tools spec + tool 执行可注入，复用 GlmApiHost 的循环/
    账本/兜底终答/重试语义）。
  - `CbmMcpHost`：cbm 二进制 MCP stdio——**会话期 tools/list 动态发现其原生工具**
    并暴露给 GLM-5.3（真·原生接口，不筛选不包装）。
  - `CliToolHost`：codegraph（explore）/graphify（query）/claude-obsidian（retrieve）
    原生命令包装为单工具；工作区副本与建库复用诊断轨适配器的 prepare 语义
    （同清单同预算；claude-obsidian 的完整形态仍是宿主 Skill 会话——适配器级原生
    检索，如实标注，与其诊断轨口径一致）。
- `tests/test_competitor_host.py`：hermetic 契约（假传输+假桥）。

## 公平性

- 同一 SYSTEM_PROMPT、同 glm-5.3、同 max_turns/预算、同 33 题干净集、同 7 族工作区
  （各系统各自的建库/索引副本）；每系统每题新会话；全程账本。
- 竞品不被调优（原生默认配置；cbm full 模式沿用健康检查结论）。

## smoke 顺序

先每系统 2 题冒烟（链路通+成本核），再 33 题全量 ×4；五系统主轨对比表入 out/。

## 回退

单提交回滚；产物在 out/。

## 边界

- 主轨答案层评分仍为机械初判/实现会话评审口径；非独立确认。
- claude-obsidian 主轨为适配器级（非 Skill 会话）——与其历史记录一致，如实标注。
