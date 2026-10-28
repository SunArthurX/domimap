# graph-sqlite — 边留在 SQLite，服务概要卡

日期：2026-10-28。计划 T9 的读取面，以及 T16 的确定性服务卡。

## 问题

`graph.json` 和 generation 文件把全部边放进一个 JSON。加载时边进入邻接表，边数上去之后进程内存跟着涨。服务全景没有「一个服务有哪些入口、表、任务」的单页。

## 预期

- `publish_generation` 在切换兼容副本之前写 `graph.db`（节点 + 边，边有 src/dst 索引）。
- `Graph.load(path, lazy_edges=True)` 在 `graph.db` 存在时只把节点载入内存，`neighbors` 按端点查询。没有 `graph.db` 时仍读 JSON。
- 应用服务默认走 lazy。迷你夹具上 lazy 与 JSON 的邻居和查询种子 id 相同。
- `Graph.service_card(name)` / `domimap card` 列出该服务的路由、表、任务、主题、RPC、文档。

## 负例

- 不存在的服务返回 None / 退出码 4。
- `graph.db` 的 user_version 高于当前进程时拒绝打开。

## 未包含

generation 文件仍是 JSON。多进程扫描、FTS、200 仓门禁不在本切片。

## 回滚

停止写 `graph.db`，`lazy_edges` 无文件时本来就读 JSON。
