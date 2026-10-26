# source-identity — D11：来源身份不由 basename 推定，节点带身份，路径可重绑

日期：2026-10-26。依据 docs/superpowers/plans/2026-10-26-drift-analysis-and-priorities.md Task 5；关闭 docs/known-defects.md D11。

## 关联需求与案例

- R01：身份与适用范围不由显示名/本地路径推定；逻辑身份、内容版本、物理路径分离。
- AC-R01-01（跨仓同 basename/同相对路径/同路由不串接，顺序无关）；AC-R01-02（根移动后显式重绑，sid 与节点 ID 稳定，持久化回读）。

## 问题

`batch.py` 以 `basename(root)` 作标签：同名两仓的 sid（`label|rel`）相同 → `sources` 行被 `ON CONFLICT(sid) DO UPDATE` 覆盖、manifest 目录相同；`route:/sql:/page:` 节点 ID 不带服务 → 跨仓同路由/同 iface.id 合并为一个节点；节点只带 rel，`evidence_map` 对重复 rel 只能"不猜"（丢链接）；`source.py` 的 SourceRegistry 零生产调用。

## 预期用户结果

- 标签：`_unique_labels(roots)` 默认目录名，冲突者追加 `~<sha256(abspath)[:6]>`；写入 manifest `label`；update/rebind 从 manifest 读回，保证稳定。
- 身份贯穿：`_stamp_sid` 给每条扫描记录 `sid=label|rel`；`Graph.build_from_records` 把 sid 戳入 Class/Method/Route/SqlStmt/Table(DDL)/Page/Doc 节点 meta。
- 证据解析：`store.EvidenceStore.evidence_by_sid()`；`store.EvidenceResolver(store).for_node(node)` 先 sid 后唯一 rel（旧图兼容），`EvidenceResolver.beside(graph_path)`；MCP `_ev_map` 与 UI `_evidence_map` 改用。
- 节点 ID：`route:<service>:<METHOD> <path>`、`sql:<service>:<iface>.<id>`、`page:<service>:<url>`（service 在多仓模式含仓标签前缀）。
- 重绑：`batch.rebind(out_dir, label, new_root)` 改 manifest.root（校验目录存在、原子写）；CLI `domimap rebind LABEL PATH -o DIR`；重绑后内容未变 → update no-op；改源 → rebuild 且非文档节点 ID 集合与 sid 集合不变。

## 设计选择

- manifest 即持久化来源登记（root/label/service_prefix/files 签名），不另起 JSON 注册表；`source.py` 保留为历史最小实装（测试引用），文档注明生产身份路径。
- 标签去重只在冲突时改名，避免为所有用户改变既有标签/服务名。
- tbl:/dom: 仍为全局名：表是跨服务共享实体；同名表/Topic 隔离属 M1.2，留档。

## Given/When/Then

- 正例：两仓同名 `svc/`、同 `docs/改价说明.md`、同 `POST /trade/price`、同 `OrderMapper.updatePrice` → 两个标签、两份 sources、两个 Doc/Route/SqlStmt 节点，各自证据读到自己的内容；[a,b] 与 [b,a] 构建节点集合相同；mini 的文件背书节点均带 sid 且有证据；去 sid 的旧节点按唯一 rel 回退；移动仓后 rebind → manifest.root 更新、update no-op、改源后 rebuild 身份不变。
- 负例：rebind 未登记标签 → KeyError（CLI exit 4）；新路径不存在 → FileNotFoundError（CLI exit 4）；未知 rel 解析 → None。

## 验证 / 回滚

见 manifest。622 tests OK（含 5 项新测试；tests/test_golden.py 四处 ID 断言随格式更新）。

## 遗留

- 冻结回放样本若引用旧格式 Route/SqlStmt/Page 节点 ID，需在新图上重新裁决（compare_runs 的 code fingerprint 维度已拒绝跨版本比较）。
- graph.json/coverage/manifest 原子发布与内容哈希签名（T6）。
