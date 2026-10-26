# impact-semantics — R04：影响面只走因果边，路径强度不高于最弱边

日期：2026-10-26。依据 docs/superpowers/plans/2026-10-26-drift-analysis-and-priorities.md Task 13。

## 关联需求与案例

- R04（有界图语义）；roadmap M2 "影响方向按关系定义，MENTIONS/领域归属不冒充因果；路径强度不高于最弱边"。
- AC-R04-02（预算在遍历中执行、partial 可见、引用完整——补齐"关系语义"侧）。

## 问题（漂移审计 §3 R04 行）

`graph.py impact()` 反向遍历无边类型过滤：文档词面 MENTIONS、领域 BELONGS_TO 被当作"谁依赖我"；`scenario.py` 的"被依赖 N 处"同样计入；全库无路径强度概念——影响面制造并不存在的因果事实。

## 预期用户结果

- `graph.CAUSAL_EDGES` 定义因果边集合；`impact()` 只沿因果边反向扩展，返回 `(src, kind, dst, strength)`，strength = 路径上最弱边置信（CONF_ORDER 最小），BFS 首达路径决定。
- `scenario_trb` 疑点卡"被依赖 N 处"只数因果反向边。
- 三入口：服务 deps 为 `{src, kind, dst, strength}`；CLI `← src --KIND(强度)--> dst`；MCP `src --KIND(强度)--> dst`；UI deps 含 `strength`。

## Given/When/Then

- 正例：doc MENTIONS t_order + t_order BELONGS_TO 域 + sql WRITES t_order + method CALLS_SQL sql + controller CALLS(AMBIGUOUS) method → impact(t_order, depth 3) 的边类型集合含 WRITES/CALLS_SQL/CALLS、不含 MENTIONS/BELONGS_TO；CALLS 路径强度 AMBIGUOUS、WRITES/CALLS_SQL 为 EXTRACTED；服务/MCP/CLI 输出含 "AMBIGUOUS"；scenario 对 t_order 显示"被依赖 1 处"（非 2）。
- 负例：无因果反向边的节点影响面为空（文档只被提及不算被依赖）。

## 设计选择

- 过滤而非降权：因果与否是语义类别，不是分数；需要词面线索的场景用 kg_explore/doc 检索。
- 首达路径强度：BFS 最短路径即用户最关心的直接影响链；不枚举全部路径。

## 验证 / 回滚

见 manifest。668 tests OK（含 4 项新测试；T8 CLI 断言随输出格式更新）。

## 遗留

- 多路径时未取"最强路径"；深度 >2 的强度解释仍是首达链。
