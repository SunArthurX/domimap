# drift-correction-c7 — 开发样例重裁决与真实改进闭环重证（F03）

依据 out/drift-audit-2026-10-26 C7。日期：2026-10-26。案例：AC-R06-06（重证）。

## 旧样例独立裁决（out/dev-ws/correction/samples-v3-adjudication.json，冻结于任何 v3 运行前）

- v1 完整题目不可恢复（run 只存 sha）——如实登记缺失，不利用结果列表猜造旧题；
  旧"零回归"结论撤回（C0 已失效 imp:ccf1ee268b695abbf2cd）。
- keep-item（fastjson asm Item.java）判 **invalid**：字节码引擎内部类与商品信息无关，
  系扩展词撞名加成产物；纠正 gold=pop-vender-ware ItemProduct（在题实体）。
- keep-stock（库存/预警/下调）与 keep-order（订单/拆单）：预警/下调/拆单 在语料
  df=0（实测），正向 gold 不可裁决 → 不入回归集、不作为负例，原文与裁决留档。
  未因候选退步而删除任何有效问题。
- 新样本集 v3（5 例，冻结 sha 3d1fe100aa0408dad0993edf96ac05c927a30d272ce39c4ff53a09f784537143）：
  目标×2（POP 主数据融合设计文档，内容核验 gold 组）+ 在题保持×2（ItemProduct/SkuUpdate）
  + 拒答负例×1；扩展词依赖且实词缺席的查询本轮无可裁决 gold，如实排除并说明。

## 重证闭环（全部真实运行；C5 纠正后的 runner/评分/门槛）

1. 基线代码（修复前）记录真实查询 → 反馈 miss（expected=精确节点）→ 诊断
   dg:02781e8b71f31e29bff00299：rerank_probe **rank_15**、ranking_defect supported。
2. baseline-v3 run rp:cdcf888fa0b86cc2：3/5（target-audit MISS；target-masterdata
   rank5 勉强过线；keep-itemproduct MISS——两轮皆 MISS，如实保留为未解决问题，
   不改 gold 不删样例）。
3. candidate-v3 run rp:ab3f271dff7bbc5f（name_tokens 限定 + EXPANSION_TOKEN_WEIGHT）：
   **4/5，verdict=improved、零回归**（目标 15→4、5→1；keep-sku 3→2；负例保持）。
4. rollback-v3 run rp:58ff1e67a078bdeb：与基线逐样本等价（激活门槛校验通过）。
5. 新启用决定 **imp:d914a167c7a25b8401fe（activated）**：lineage 完整（簇/诊断/
   三 run/回滚等价/真实代码指纹）；追溯链 out/dev-ws/correction/evolution-trace-v3.json。

## 范围声明

开发语料（真实企业工作区）上的小样本结论（5 例）：证明本切片的修复有效且回归受控，
不外推总体优越性；正式生产/四竞品验收仍按原规范独立进行。

## 验证

- 全链真实命令与 run 记录（上文 ID）；
- `python3 -B -m unittest tests.test_evolution_replay tests.test_identifier_ranking -v`；
- `make verify`（收尾统一）。

## 回滚

排序修复单独回滚=revert search.py 精确差异（rollback-v3 已实证等价基线）；
imp:d914a167c7a25b8401fe 可追加 rejected/rolled_back 记录。

## 文件

specs/tasks/drift-correction-c7.{json,md}、out/dev-ws/correction/*（工件）；
domimap/search.py 不在本片改动（候选策略即现状代码，仅作基线/回滚切换验证）。
