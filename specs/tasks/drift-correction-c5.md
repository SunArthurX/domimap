# drift-correction-c5 — 可信回放与启用门槛重建（F02/F04）

依据 out/drift-audit-2026-10-26 C5。日期：2026-10-26。案例：AC-R06-06/07（贡献纠正，最终收敛见 C7）。

## 修复（tests/test_evolution_replay.py 重写为 15 项，先失败后通过）

- 精确证据评分（F02，probes: same_file_wrong_node）：期望必须是精确节点身份
  （expect={"node"|"nodes"}）；主候选（非扩展项）中期望节点首次出现位置即名次；
  同文件错误节点=miss；旧名称/路径子串格式（expected 字段）加载即拒绝并明示废弃。
- 可选层显式关闭（probes: replay_optional_layers）：semantic/rerank/embed 显式
  False，环境开关不得重新启用。
- 冻结 manifest（F04）：run 记录 runner/scorer/样本摘要/图（mtime/size/nodes）/
  知识代际/词表指纹/代码指纹；compare_runs 校验冻结维度一致、样本集合完整相等
  （缺/多均拒）；缺 manifest 的旧 run 仅作历史不可比较；params_json 记真实值，
  逐样本绑定 event_id 与候选 id 快照；source_fingerprint None→unknown。
- activated lineage 门槛（probes: invalid_activation）：簇必须存在；diagnosis_id
  必填且属于该簇；candidate 判定 improved；候选指纹非 unknown；rollback run 与
  基线逐样本等价且代码指纹相同（真实回滚演练）。
- chain 限定（F04）：只显示 replay_cluster_links 关联或 improvements 引用的 run；
  replay CLI --cluster 建立关联。

## 验证

python3 -B -m unittest tests.test_evolution_replay -v（15/15）。

## 回滚

revert replay.py/__main__.py 差异；replay_cluster_links 表可 DROP；旧 run 保留。

## 文件

domimap/replay.py、domimap/__main__.py、tests/test_evolution_replay.py、
specs/tasks/drift-correction-c5.{json,md}。
