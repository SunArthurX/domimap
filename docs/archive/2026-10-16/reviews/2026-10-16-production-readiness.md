# domimap 生产准备度复核

日期：2026-10-16。目标：根据全部既有讨论与当前项目，重新制定生产知识库和 GitHub 开源计划。交付是[新主计划](../../../roadmap.md)与[架构边界](../../../architecture.md)，不是功能实现或发布。

## 1. 结论

保留 Java 多仓和框架规则资产，定位扩展表述为人和 Agent 共用、可追溯和可维护的本地知识库。当前 v0.4.0 是原型；生产化的关键缺口是数据身份/证据、持久事务/恢复、应用契约、知识维护、入口兼容及公开发布工程。

此前六个工作包覆盖了很多功能，但安全/并发/迁移/分发底线较晚，第一性原理建议没有全部变成主线验收，SQLite 被视作性能条件增强，GitHub 准备偏向收尾。新计划前移这些工作，保留用户四项明确要求，设置生产门槛与逐项证据。

## 2. 本轮证据与范围

机器记录：[production-audit.json](2026-10-16-production-audit.json)。源码、测试、配置、计划和历史审计均作了重新读取。新测试只在临时副本/合成目录运行，不扫描真实业务仓、不改产品 Python 源码、不修改客户端配置。

| 检查 | 本轮结果 | 能证明/不能证明 |
|---|---|---|
| 现有测试 | 22/22 通过，macOS、Python 3.14.4 | 原型回归可运行；没有覆盖所有生产契约 |
| 单独运行索引缓存测试 | 干净副本只运行 TestIndexCache，缺 graph.json 失败 | 存在测试顺序/产物依赖；不代表缓存每次都失败 |
| 原始 Top-5 | 沿用旧接受名称串、不使用场景兜底，6/8 | 可复核历史指标问题；仍不是新的独立 ID/证据 gold |
| 丢失派生图 | 删 graph.json 后再次 build：no-op，图仍不存在 | 当前完整性检查不足 |
| MCP 非法请求 | JSON 数组后接合法 ping，进程 AttributeError 退出，ping 未获响应 | 当前请求类型检查/服务容错不足；不是远程渗透测试 |
| MCP schema | kg_explore.required 在 inputSchema 外 | 工具入参契约错误；不等于所有客户端必然拒绝 |
| 符号链接边界 | 合成允许根内链接指向根外 MD，正文被摄入且无 skip | 当前允许根边界没有实现；未读取任何真实外部资料 |
| 仓库工程 | 无 Git/父 Git；有 .gitignore，缺 LICENSE/CONTRIBUTING/SECURITY/CHANGELOG/.github/workflows | 有工程与开源准备缺口；pyproject 首页不能证明远端已存在 |
| 本地安装能力 | Python 无 setuptools，有 wheel；未为本次分析安装构建后端 | 本轮未验证新分发物；不据此说项目正常构建必失败 |
| 客户端发现 | PATH 有 claude/codex，无 zcode/dsh | 只是定位线索，四端均没有本轮实际联调证据 |

同名实体、SQL 构建顺序、manifest 提前更新、缓存完整性、图方向等本轮通过源码复核，与[初轮诊断](2026-10-16-baseline-audit.json)一致；没有将旧实验改写为本轮全部重跑。

第一性原理轮的高出度 2,000 邻居、重复来源占满 Top-5、版本混合，以及 PRD/SQL 乐观锁差异保留在[原诊断记录](2026-10-16-first-principles-evidence.json)。它们是合成/夹具实验，不能推出真实生产缺陷率。

## 3. 上游观察

核查对象与前轮相同，避免使用同名项目混淆。官方 README 用于确认设计方向，GitHub API 用于记录可定位的参考提交和许可证元数据；没有安装、性能复现或选型胜出结论。

| 项目 | 参考提交 | API 许可证元数据 |
|---|---|---|
| [AgriciDaniel/claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian) | `32ac5a02c4e082e4a5628ca810776375e134708e` | MIT |
| [DeusData/codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) | `ec6427c38176efcd37b28682e82f2491afda94be` | MIT |
| [colbymchenry/codegraph](https://github.com/colbymchenry/codegraph) | `98127e54d0090723855dd098e7badf211c6de437` | MIT |
| [Graphify-Labs/graphify](https://github.com/Graphify-Labs/graphify) | `10130e79ed9caf8f60d998073e097531eaa1a395`，默认 v8 | Apache-2.0 |

版本会继续变化，这些不是未来依赖锁。真正复用时固定所选版本、读取分发文件、记录部署与维护代价，不根据元数据直接判断全部兼容或无需通知。

附加官方依据：[SQLite 适用边界](https://www.sqlite.org/whentouse.html)、[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)、[MCP 版本规范](https://modelcontextprotocol.io/specification/latest/basic/lifecycle)、[GitHub Actions 安全使用](https://docs.github.com/en/actions/reference/security/secure-use)、[Python 包元数据指南](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)。这些只支持对应工程设计，不证明本地功能已具备。

## 4. 全项目处置建议

| 当前模块 | 处置与下一步 |
|---|---|
| lite_scan.py | 保留基线/框架经验；捕获来源字节、身份/位置契约、允许根、coverage 和有界解析；AST 方案经小试验决定 |
| graph.py | 统一 ID，先节点后关系，命名空间与候选状态、按关系的查询方向；保留 JSON 导出 |
| batch.py | 保留发现/调度入口；修 root/label、配置失效、发布/恢复；先正确后增量复用/监听 |
| search.py / tokenize.py | 保留中文与标识符词法基线；分路片段召回、范围/去重/时间、读取证据与遍历预算 |
| mcp.py | 工具语义保留，协议适配迁官方 SDK；schema/协商/容错/预算/只读与写入隔离 |
| scenario.py | 保留需求/调查展示，调用公共查询；取消混合指标，静态线索不冒充运行根因 |
| __main__.py | 保留现有入口并提供迁移；显式知识库、JSON/稳定错误、安装后任意目录可用 |
| 新的持久层/应用服务 | 来源/代际事务、知识/claims/审定、幂等/冲突/迁移/备份；不要散落在各 UI/协议层 |
| tests | 夹具继续作 smoke，纠正已编码的合并语义；补独立 gold、故障/边界/并发/格式/平台验证 |
| pyproject / setup / Makefile | 实际支持版本/extras、包资源/许可证、干净安装；安装脚本不得吞测试失败或隐式安装全部能力 |
| README / docs | 一个生效主计划，当前能力与待实施分开；旧性能和回放口径保持边界 |
| 生成物 / 业务资料 | 产品源、运行数据、公开工件分离；上传前检查实际 allowlist 与历史 |

`setup.sh` 当前在管道后取 tail，没有 pipefail，会掩盖测试失败；同时 doctor 将 platform.version 当作 Python 版本，且导入 graphify 并不代表已经接入。这些列入 M0/M2 工程修正，不在本次文档调整中偷偷实现。

## 5. 对“生产”的完成定义

生产目标不能靠新增 TODO 数量判断。主计划给出需求 R01–R12 与 F1–F4、M0–M5 依赖、硬门槛、独立任务评估、候选资源预算和开源工件检查。所有候选性能值明确未测；现有 22 项绿灯不能充当这些未执行的检查。

推荐首发为本机单所有者、多会话知识库，依据此前本地/离线/多客户端方向；团队远程服务保留独立演进边界。没有暗中把多客户端并发删成单进程，也没有把 ZCode/DSH 或人工界面删除。

本轮完成范围是分析与计划整合。产品成熟度、许可证文件、CI、迁移、界面、客户端适配和 GitHub 上传均保持待实施；应按新主计划从工程基线开始。
