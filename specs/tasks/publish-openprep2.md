# publish-openprep2：公开前的图谱文档、语料脱敏与社区配套

- 关联：R13（可执行防偏离约束，AC-R13-01）。延续 publish-openprep，属文档与验证工具整理，不改产品行为。
- 来源：用户 2026-10-20 指示——①补图谱模型文档（"让 AI 和人理解"）；②脱敏必须删除指明公司的代码，替代语料可考虑网上开源语料；③社区配套。

## 正例 / 负例

- 正例：`docs/knowledge-graph.md` 与 `domimap/graph.py`/`search.py` 的类型一一对应（12 类节点、11 种边、conf/prov 语义、证据层、时间模型、检索数据流）；README/docs 索引可达。
- 正例：语料脚本在未设置 `DOMIMAP_DEV_CORPUS` 等环境变量时，模块仍可导入（契约测试依赖此），入口函数以明确错误退出并指向 `benchmarks/DATA_LAYOUT.md` 的自备语料指引（含开源语料构建方法：≥20 个不相关开源族 + isolation 独立簇校验）。
- 负例：仓库跟踪文件与全部历史 blob/提交信息中不得出现公司名、内部语料名（含包名、族名、内部目录名）与个人主目录路径；终扫（全部 revision 的 git grep + 全对象流扫描）必须为 0。
- 负例：`test_corpus_isolation.test_short_token_not_merged` 保持语义——夹具改名后共享 token 仍须 < 4 字符（"qr"），防止把"短 token 不并簇"改没了。

## 实施

1. `benchmarks/corpus/{generate_fact_gold,generate_questions,generate_questions_v2,isolation,manifest}.py`、`benchmarks/runners/{dev_pilot,dev_score,gold_review}.py`、`benchmarks/formal_run.py`、`benchmarks/real_tasks/run.py`：语料根 → `DOMIMAP_DEV_CORPUS`；外部文档族列表 → `DOMIMAP_EXTRA_FAMILIES`；文档优先族 → `DOMIMAP_DOC_FAMILIES`（dev_pilot，原内置族名集合外置）；预建图 → `DOMIMAP_DEV_GRAPH`（缺省 `out/dev-idx`）。测试导入的模块保持导入安全（env-or-空 + 入口守卫），纯脚本模块导入即报。
2. 测试夹具脱敏：Java 包名改 `com.example.*`，隔离层夹具族名改 `corp-*`/`qr-*`（`qr` 保持 <4 字符共享 token，"短 token 不并簇"语义不变）。
3. `specs/tasks/` 五个历史任务记录与 `benchmarks/real_tasks/tasks.json` 的公司名/内部路径表述中性化（"企业语料（私有）"）。
4. `benchmarks/DATA_LAYOUT.md` 增"自备语料"一节：环境变量表 + 企业私有/开源语料两条路径。
5. `docs/knowledge-graph.md`（新）：基于源码核实的图谱 schema 参考。
6. 社区配套：`.github/ISSUE_TEMPLATE/`（bug/feature/usage）、`PULL_REQUEST_TEMPLATE.md`、`CODE_OF_CONDUCT.md`；`docs/clients.md` 头部加"开发期状态记录"说明；README 补 `kg_troubleshoot` 工具行与图谱文档入口；docs/README 索引挂接；CHANGELOG 记一行。

## 验证与回退

- `python3 -B -m unittest tests.test_corpus_isolation tests.test_comment_recall tests.test_gbk_read tests.test_identifier_ranking`；`make verify`（refresh_evidence 后）；新克隆 + 干净 venv `make ci`（benchmarks 模块导入安全性）。
- 回退：revert 本提交即恢复原硬编码路径（不建议——公开仓库不得回带公司名）。
