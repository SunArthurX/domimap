# generation-consistency — RV01：图/证据/清单同一不可变代，中断不混用、不误报 no-op

日期：2026-10-27。依据 out/agent-review-2026-10-27/review.md RV01（两个中断反例已复现存档 generation-reproductions.json）。

## 问题

1. 来源捕获与新 manifest 在图发布**前**写入；EvidenceResolver 按 sid 查**最新**证据（meta source_evidence 指针），不绑定图所在代。反例 A：文档 v1→v2，发布前中断 → 搜索图仍 v1、节点解析到的证据已是 v2；再次 update 因 manifest 已更新而 no-op，混用状态永久化。
2. 反例 B：store 切代后、graph.json 兼容副本落盘前中断 → graph.json=v1 而 active 代=v2，解析仍取最新（v2）→ 混用窗口（后续 update 能重建，但窗口内不一致）。

## 修复

- 代绑定来源版本：`publish_graph(g, extra_meta={"sources": {sid: {repo, rel, sha256, ev_id}}})`——构建期捕获返回值收集为该代的 sources 映射，随不可变代一起发布。
- 请求固定版本：`EvidenceResolver.beside(graph_path)` 先取 graph.json 字节 sha → 在 generations 表按 sha 定位**该图所属的代** → 用该代 meta.sources 解析 sid；旧代无 sources 键时回退最新指针（兼容）；rel 回退不变。
- no-op 依据已发布状态：各仓 manifest.json 移到 `publish_generation` **成功之后**原子写入；发布前中断 → manifest 未动 → 下次 update 重建（不再 no-op）。
- `_store_healthy` 既有 graph.json sha==active 代 sha 校验保留（反例 B 由它触发重建；窗口内由代绑定解析保证一致地服务旧版）。

## Given/When/Then

- 正例：v1 build → 改 v2 → 注入 publish_generation 抛错 → 节点解析证据文本仍=图文本=v1；真实 update 重建（非 no-op）后图/证据=v2 一致。注入切代后 graph.json 落盘前中断 → 解析仍 v1（按图 sha 定位旧代）；下次 update 重建。
- 负例：未发布捕获不得改变旧图解析；旧代（无 sources）回退路径可用。

## 验证 / 回滚 / 遗留

见 manifest。遗留：多写入者并发发布同一工作区仍靠 SQLite EXCLUSIVE 串行（既有）；跨进程同时读旧图+新代时按图 sha 各自一致。
