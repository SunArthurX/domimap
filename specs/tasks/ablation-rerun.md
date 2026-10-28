# ablation-rerun — AC-R12-02 诚实重验：当前源码三配置消融

日期：2026-10-28。依据 review.md RV06（旧消融报告 results 非空 ≠ 当前源码证据）。

## 修复与执行

- 新增 `benchmarks/runners/ablation_local.py`：同题集（dev-gold-v2.1 33 题，gold 只带路径——query 从 dev-questions-v2 按 id 关联，缺题 KeyError 如实失败）、同预算（top_k=5、单次确定性）三配置：text_only（不挂知识+expand=False）/ text_plus_graph / text_graph_knowledge（挂图旁 knowledge.db）。
- 当前源码新建 dev 图（out/dev-abl，--discover 45 仓，270210 节点，新 ID 格式：方法签名/服务限定表）。
- 结果（out/verification/m5-ablation-v2.json，绑定源码指纹+图 sha+题集 sha+命令）：三配置 Hit@5 均 0.5172（29 正例），负例正确 0/4（4 条 abstain 题均返回弱候选而非拒答——真实弱点，记录在案不粉饰）；三配置在本图上无差异（该图 knowledge.db 为空、图扩展在同池——差异如实为零）。
- progress：AC-R12-02 以 v2 证据回 verified（诚实降级解除）；reverify_cases 的 R12-02 命令改为真实重跑（不再查旧报告）。

## 边界

诊断轨口径（路径级 Hit@5/拒答），非主轨 Accuracy/F1；不外推；不改变 R14 门槛。
