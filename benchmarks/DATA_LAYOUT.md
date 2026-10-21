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

## 自备语料（Bring Your Own Corpus）

仓库**不携带任何私有语料**。`benchmarks/corpus/` 与 `benchmarks/runners/` 里的生成/试点脚本通过环境变量定位语料，未设置时在入口明确报错（保持模块可导入，契约测试不依赖语料）：

| 环境变量 | 用途 | 使用者 |
|---|---|---|
| `DOMIMAP_DEV_CORPUS` | 语料根目录（其下每个子目录 = 一个来源族） | corpus 生成器、isolation、manifest、formal_run、dev_pilot/dev_score、gold_review |
| `DOMIMAP_EXTRA_FAMILIES` | 逗号分隔的额外文档族路径（补 document_reasoning 配额） | generate_questions_v2、isolation、manifest、gold_review |
| `DOMIMAP_DOC_FAMILIES` | 逗号分隔的文档优先族名（工作区选择的种子） | dev_pilot |
| `DOMIMAP_DEV_GRAPH` | 预建图路径（缺省 `out/dev-idx/graph.json`） | real_tasks/run.py |

语料两种来源皆可：

1. **企业私有语料**：本地多仓工作区（对外只出现"企业语料"这一中性称呼，产出物中的族名/路径不入库）。
2. **开源语料（推荐用于复现/新评测）**：从 GitHub 克隆 ≥20 个**互不相关**的开源项目族放入同一根目录，跑 `python3 benchmarks/corpus/isolation.py` 验证独立簇数满足协议下限（同字节样板如 mvnw/LICENSE/.DS_Store 不算关联，isolation 已内置排除）。README 公开语料基准（27 个未暴露开源族 × 40 题）即按此方法构建。
