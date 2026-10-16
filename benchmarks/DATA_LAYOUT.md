# 比较数据隔离设计（dev / 确认）

对齐 specs/benchmark.md 与 AGENTS.md：确认 gold 不进实现 Agent 可读目录；开发只碰 dev。

## 目录边界

```
<外部基准根>/                 # 不在 domimap 仓库内（实现 Agent 不可读确认部分）
  corpus/
    dev/                      # 开发语料：来源族编号 dev-01..（合成 + 已授权公开仓）
    confirm/                  # 确认语料：≥300 可回答 + ≥100 不可直接回答 + ≥20 独立来源族
  gold/
    dev.json                  # 开发标注（可用）
    confirm.json              # 确认标注：实现会话不可读；仅独立运行器/裁决者使用
  runs/                       # 五系统原始输出 + 映射 + 哈希（只追加）
  adjudication/               # 盲化裁决工件

domimap 仓库内：
  benchmarks/tiny_dev/        # 仅 tiny spike（合成夹具 + 少量开发观察题），不含确认数据
```

## 隔离规则

1. dev 与 confirm 的**来源族不相交**（按语料顶层目录编号隔离；同一项目族不得同时出现在两侧）。
2. 确认批次运行前冻结：源指纹、五系统版本、预算、种子、gold 哈希——预登记到 runs/manifest。
3. 实现会话需要新确认批次时，另行登记新来源族并保持独立（多次检验控制）。
4. tiny_dev 属 dev 性质（合成夹具 + 开发观察），其命中不进入任何正式指标。

## 公共输出映射（五系统 → 统一 JSON）

每系统适配器输出：`{"system", "question_id", "candidates": [{"path", "line?", "snippet?", "score?"}...≤10], "raw_ref": <原始输出工件>}`。
评分只取前 5 主证据位置（Hit@5）；canonical 映射（各系统路径形式→语料相对路径）随适配器登记并在 runs/ 留样。
