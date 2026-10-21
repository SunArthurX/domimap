# comparison-dev-questions-v2：dev 题集语义修正 + 40 题五方诊断轨试跑（测试计划第 4 步前置与执行）

来源：计划 §4.2（内容与难度）、§1.2 P0#6（问题语义缺陷）、§9 步骤 4。
性质：**评测基础设施 + 试跑执行**。

## 修复的旧语义缺陷（generate_questions.py 实证）

| 旧缺陷 | 旧代码 | v2 语义 |
|---|---|---|
| 文档理解=标题/README 文件名检索 | docs=标题成题、README 文件名兜底 | 查询词来自文档**正文**（限制/例外/前提句的主题词），显式排除标题与文件名词；必要事实=正文原句 |
| 时效=mtime 最新文件 | `sorted(fresh, reverse=True)` | 只用**文档内**日期/版本陈述（20xx 年月日、vN.N、生效/替代标记）；mtime 绝不参与（负例测试：touch 后题目不变） |
| 定位全为标识符串查 | query=表名/类名 | 标识符题 ≤40%；≥60% 用类/方法邻近**中文注释关键词**成题（内容→位置，非文件名→位置） |
| 负例=双字母变形 | `t[:-2]+"zx"` | 四因负例：无证据（grep 验证缺失）/近名（编辑距离验证）/歧义（同名双仓验证存在）/错范围，各带验证方法记录 |
| 题与 gold 同文件、含 family | questions.json 混装 | questions（id/category/query）与 gold（family/paths/facts/disposition/verify）**分文件**；运行器拒收 gold 字段（已有契约） |

## 类别与配额（dev 160+20）

code_location 30、cross_repo_trace 30、document_reasoning 30、knowledge_freshness 30、**locator_diagnostic 20（单列诊断，不入四类）**、negative 40（10×4 因）。四类=正例主体；locator 不冒充文档推理。

## 试跑（计划步骤 4 的诊断轨部分）

1. 试点选择：40 题 = 四类各 8 + locator 4 + negative 4，题的 gold 家族 ⊆ 5-6 个较小 dev 家族构成的公开工作区（全系统同清单，无 gold 路由）。
2. `run_batch(repeats=[11])` 五系统各一遍；另抽 5 题 `repeats=[11,23,37,53,71]` 验证五次独立记录。
3. 核对：记录数恰等、run_id 唯一、原始工件在、错误分类矩阵、每记录 secs 预算、env-skip 如实。产出试跑报告 out/diagnostic-runs/pilot-report-v1.json。

## 契约（测试）

1. mtime 无关性：同语料 touch 全部文件后重新生成 → 题集字节不变。
2. freshness gold 含文档内日期/版本串且该串真实存在于 gold 文件内容。
3. doc_reasoning 查询不含 gold 文件名主干/文档标题。
4. locator 类别独立且标注 diagnostic。
5. questions 文件无 gold/family 键；gold 文件有 verify_method。
6. 负例四因各有验证记录；无证据负例 grep 全工作区确认缺失。
7. 配额满足；确定性（两次生成一致）。

## 回退

单提交回滚；out/ 生成物可重生成。

## 实测结果（2026-10-17 真跑，企业语料 45 族）

- 生成 **163 题**：code_location 30 / cross_repo_trace 30 / document_reasoning 30 / knowledge_freshness 13 / locator_diagnostic 20 / negative 40（四因各 10）。
- **时效类 13/30 为语料事实**：企业语料 dev 侧带文档内日期且主题词合格的素材仅 13 个（不注水：不用 mtime 补数正是本任务目标）。确认候选的公共语料（docx/文档丰富仓）将补足该类。
- **两次实跑暴露的语料真相与修复**：①企业中文文档多为 GB18030（utf-8 replace 读成乱码使中文正则全失效）→ utf-8 严格失败回退 GB18030；②文档族纯文本 .md/.txt 仅 2 个，知识在 .docx/.html（315+42 个）→ stdlib zipfile+去标签机械抽取（grep 级，非产品管线）；③单一大正则抽类注释在 200KB Java 上 O(n²)（22 分钟未完成）→ 两遍法秒级。
- 外部 4 文档族（各 1.8-2.0GB）扫描代价过高且非目标负载，dev v2 收敛企业语料 45 族。
- 契约测试 9 项绿（mtime 无关性、正文成题非标题、定位单列、题/gold 分文件、四因负例带验证、标识符 ≤40%、跨仓 ≥2 族、确定性、无 gold 字段）。
- 试点：40 题（四类各 8 + locator 4 + negative 4）⊆ 7 族工作区（16,456 文件；跨仓 gold 集合种子贪心选定——纯最小族贪心曾致 cross=0）。

## 试跑结果（2026-10-17 真跑，out/diagnostic-runs/pilot-report-v1.json）

- **integrity_problems = 0**：记录数恰等（40 批 200 条 = 5 系统×40 题；5×5 批 125 条 = 5 系统×5 题×5 重复）、run_id 唯一、原始工件齐全、无预算超限、env 零跳过。
- 错误分类（40 批）：ok 148 / product_empty 52 / **无 error、无 timeout、无 env_error**——五系统全部健康，空结果即真实检索行为（含 4 负例的合理拒答）。
- 每系统（40 批）：domimap 38 ok+2 empty（0.7s）、claude_obsidian 40 ok（92.1s）、cbm 36 ok+4 empty（5.5s）、graphify 21+19（230.7s）、codegraph 13+27（81.1s）。
- domimap 跨仓查询返回多仓证据（seller.shop+seller.man 路径同列 top5）——无 gold 路由下的跨仓访问实测有效。
- 过程处置（如实）：claude-obsidian contextual 分块走本地 ollama，无页上限时每族 8-15 分钟（首次试跑 23 分钟仍在 prepare）→ 试点预算页上限 300+prepare 420s，截断逐仓记账；首个超时批次作废重跑（diag-cb480a14aa01 弃用，未计入报告）。
- 5×5 批：五重复独立记录验证通过（确定性系统输出相同、run_id/工件独立）。

## 第 2 轮增补：gold 质量过滤（2026-10-17，第 5 步诊断驱动）

- 诊断实证：sy_html 等 mock 页占位文本（"谁谁谁/啥啥啥"）被 topic_words 当主题词，产出不可检索的假 recall miss（短查询实测亦无法命中——文档正文无实质主题词）。
- 修复：`mock_ratio`（占位 token 占比，含单字符重复≥3 的 aaaa/1111 型）> 0.02 的文档不参与 doc/freshness/locator 成题；topic_words 同步排除占位 token。回归测试 test_mock_pages_excluded_from_gold。
- 重生成后总数不变（163）：mock 题被同族其他合格文档替换。
