# comparison-native-adapters：五方诊断轨原生适配框架（测试计划第 2 步）

来源：`out/test-plan/2026-10-17/完整竞品测试计划.md` §11.2 任务 2、§3（五方原生适配与公平条件）。
性质：**评测基础设施**。本切片完成诊断轨适配框架与五适配器的 dev 契约；主轨（共同宿主真实 Agent 会话）适配仍阻塞于模型凭据，不在此列。

## 修复的 P0 缺陷（旧 formal_run.py 实证）

| 缺陷 | 旧代码位置 | 新框架契约 |
|---|---|---|
| gold 首仓路由 | `q["family"].split("+")[0]` ×4 处 | `query(question_id, text, budget)` 签名无任何 gold 字段；适配器只见公开工作区清单，跨仓统一合并策略（manifest 序 round-robin，无 gold 信息） |
| 单方来源截断不记账 | claude-obsidian 400KB/800 页静默截断 | 截断保留但**逐仓公开记账**（页数/字节/排除数入 PrepareReport.accounting） |
| 吞索引错误 | `except Exception: pass` | prepare 逐仓记录 ok/failed 与原因；失败仓显式呈现，不冒充空结果 |
| 正则抽路径当输出 | 4 个适配器展示文本正则 | 结构化输出优先；正则兜底规范化为仓相对路径，未映射 token 计数入 notes |
| 无独立运行记录 | 单次确定性覆写 | 每查询独立 run_id、起止时间、状态分类、原始输出工件、错误分类 |

## 架构

```
benchmarks/adapters/
  base.py        # ErrorClass(ok/product_empty/product_error/env_error/adapter_error/timeout)
                 # RepoEntry/PrepareReport/QueryRecord/Adapter 基类
  envs.py        # 四竞品环境探测（版本证据 + 入口存在性；缺失→SKIP 不算零分）
  devfixture.py  # 契约测试合成工作区（3 仓：中文名文件/重复内容/同名符号/空仓/长输出）
  domimap_adapter.py       # 聚合图（原生多仓）
  cbm_adapter.py           # 逐仓 index_repository(full) + 全项目查询合并
  graphify_adapter.py      # 逐仓 update + 全仓查询合并
  codegraph_adapter.py     # 逐仓 init/index + 全仓 explore 合并
  claude_obsidian_adapter.py # 逐仓 vault + setup-retrieve + 检索合并（截断记账）
tests/test_adapters_contract.py  # 每适配器 ≥20 契约样例 + 框架级反路由断言
```

## 契约（每适配器 ≥20 dev 样例覆盖）

正常命中、空结果、多仓命中去重、中文查询、中文文件名、空格路径、重复内容文件、同名歧义、超时、缺索引先查、二进制缺失(env)、坏仓目录(prepare 记录)、长输出(top5 恰 5)、特殊字符查询、未映射输出(product_empty+notes)、prepare 后重复查询状态一致、预算/耗时记录、run_id 唯一、原始输出逐字保存、查询接口无 gold 字段（框架级反射断言）。

## 负例

1. 适配器 query 收到 gold family → 框架测试断言签名不存在该参数。
2. prepare 失败仓被静默跳过 → 契约要求 failed_repos 显式记录（坏仓样例断言）。
3. 超时被当作空结果 → 契约要求 error_class=timeout 与空结果区分。
4. 环境缺失被当产品失败 → envs 探测失败时 SKIP（不计分），非零分。

## 回退

单提交回滚；旧 formal_run.py 与历史 runs 不受影响（新代码独立成包）。

## 边界

- 不改 domimap 产品代码；不引入新依赖；不触历史工件。
- 主轨 Agent 适配（claude-obsidian 原生 Skill 会话等）待模型凭据，另行任务。
- 本任务不完成 AC-R14-01（比较本身）。
