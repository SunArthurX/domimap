# comparison-dataset-isolation：内容级清单与来源关联簇（测试计划第 3 步）

来源：计划 §11.2 任务 4、§4（数据集）、§1.2 P0/P1 缺陷项。
性质：**评测基础设施**。修复两个已审计缺陷；不改产品代码。

## 修复的缺陷

| 级别 | 缺陷 | 旧依据 | 新实现 |
|---|---|---|---|
| P1 | 族内容摘要 = 路径+大小哈希，同大小内容修改不可检 | benchmarks/corpus/manifest.py family_signature | 逐文件字节 SHA-256 清单（path/size/sha256），族签名 = 对 (relpath,size,file_sha) 有序哈希；v2 输出到新文件，旧 corpus-manifest.json 保留 |
| P0 | 70 cluster 中 41 个多族组合被当独立样本；组合≠独立族 | 旧 bundle cluster 统计 vs 28 真实族 | 来源关联图连通分量：①内容同一性边（同文件哈希跨族，排除 <256 字节样板）②旧题组合边（已暴露 dev 资产的 176 个多族题）③前缀启发式边（首 token ≥4 字符，文档化）；报告同时给出含/不含启发式的簇数，**独立性声明取保守值（较少簇）** |

## 交付

- `benchmarks/corpus/isolation.py`：v2 清单 + 簇报告 + 预登记草案生成（batch_id/UTC/各工件哈希/候选指纹；独立保管人字段留空）。
- 运行产物（dev 可见）：`out/benchmark/corpus-manifest-v2.json`、`out/benchmark/cluster-report.json`、`out/benchmark/preregistration-draft.json`。确认侧题目/gold 不在本仓库生成（独立环境缺位如实登记）。
- `tests/test_corpus_isolation.py`：合成夹具契约。

## 契约（测试锁定）

1. 同大小不同内容 → 族签名必变（P1 回归）。
2. 内容同一性：两仓共享一字节相同文件（≥256B）→ 同簇；无共享 → 异簇。
3. 组合边：{A+B} 题使 A、B 同簇。
4. 前缀启发式：同首 token（≥4 字符）→ 同簇；报告给出含/不含启发式两口径。
5. 确定性：同树两次运行签名/簇一致。
6. v2 schema：families[].files_inventory 含 path/size/sha256；无正文泄漏。
7. 预登记草案：含 batch_id/UTC/哈希表；sealed_by 为空（未封存）。

## 负例

1. 改一字节（保大小）重算 → 签名变化必须被检出（反"机械刷新"）。
2. 孤立族不被并入任何簇（无边即单族簇）。
3. 预登记缺哈希字段 → 生成器报错。

## 回退

单提交回滚；out/ 下 v2 产物为生成物可重生成；旧 manifest/bundle/report 未触碰。

## 边界

- 独立评测环境（独立用户/机器/保管人）是外部条件，本任务只产出 schema、工具与可移交工件；最终确认未完成不宣称。
- 新题集（dev 160/选型 80/确认 480）与双标 gold 属后续任务。

## 实测结果（2026-10-17 真跑，48 族 = 45 个 ~/work/dev-corpus 仓 + 4 个外部文档族）

- **独立簇远低于协议下限**：strict=14、conservative=12（协议要求 ≥20；计划建议 24）。dev-corp 业务核心为 32 族巨型连通分量（164 条内容同一性边 + 48 条旧题组合边 + 前缀边）；bingo 系 5 族同簇；deepseek-harness 与 saber-harness 共享 harness 样板归同簇；westpath/zhiyu 独立。
- **规则迭代一例（有测试回归）**：首版把 .DS_Store（macOS 元数据，全机同字节 6148B）当内容同一性边，把无关族连成假簇（strict 曾=9）；排除系统元数据/点文件后修正。教训入契约测试 test_os_metadata_files_do_not_create_edges。
- 含义：①旧 bundle 的 70 cluster（41 个多族组合）按真实关联只有 12-14 个独立抽样单位，旧 20000 次 bootstrap 的置信区间显著高估自由度；②dev(20)/confirm(28) 的族级分片在内容上隔离，但 dev-corp 侧共享同一巨型来源关联簇；③**当前语料不可能满足冻结协议的 ≥20 独立族**——必须补 ≥8 个真正无关的新来源族（公共开源语料或用户授权来源），此事属语料扩充后续任务，不得缩协议迁就现状。
- 产物：out/benchmark/corpus-manifest-v2.json（逐文件 path/size/sha256，共 48 族）、cluster-report.json（两口径簇 + 全部边 + 排除规则）、preregistration-draft.json（batch-xxx 草案，sealed_by 空）。
- 契约测试 12 项绿（P1 同大小改内容检出、小样板/.DS_Store 不造边、组合/前缀边分离口径、确定性、schema、预登记缺哈希报错）。
