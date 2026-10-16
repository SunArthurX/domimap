# domimap — 多仓 Java 知识库原型（v0.4.0）

Domain + Map：把多个 Java 仓库与项目文档变成一张可查询的领域地图（CLI + MCP）。
本机优先（macOS / Windows / Linux），核心**零第三方依赖**（纯 Python 标准库），
可选依赖仅增强；当前主要以本地单用户方式验证。

**生产化方向（2026-10-16）**：建设人和 Code Agent 共用的本地知识库，以 Java 多仓、项目资料和人工结论贯通第一条用户路径；支持独立文档目录，逐步达到可恢复、可维护、可开源的交付标准。当前实现仍为 v0.4.0 原型。
文档入口：[文档导航](docs/README.md) · [生产主计划](docs/roadmap.md) · [开发约束](specs/workflow.md) · [完整开发 Prompt](docs/prompts/implement-to-completion.md)。历史分析统一归档，当前能力与计划分开记录。

生产路线从 M0 工程基线开始；计划中的 SQLite、界面、知识保存与新客户端适配仍待实施，详见主计划。

| 能力 | 当前状态 |
|---|---|
| Claude / Codex / ZCode / DSH 快速接入 | 有 MCP stdio 基础，四客户端连接适配与联调待做 |
| 人工手动搜索 | CLI 已支持；本地交互搜索页待做 |
| AGENTS.md / SOUL.md | 可作普通文档摄入；可信规则/轻量人设加载与桥接待做 |
| 文档时间衰减 | 尚未实现；缓存 mtime 不代表内容时效评分 |

**当前边界**：同名方法与跨仓同路径文档可能合并；人审目前仅导出待审页；源码变化需主动更新。现有 8 条夹具的原始 Top-5 为 6/8（75%），旧测试报告 8/8 使用了场景卡兜底，尚未完成真实任务验收。

## 三条命令跑通

```bash
python3 -m domimap build tests/fixtures/mini -o out          # 建图（节点/边数量以当前输出为准）
python3 -m domimap query "订单改价 防并发 price_version" -g out/mini/graph.json   # 混合检索
python3 -m domimap domain  -g out/mini/graph.json            # 领域地图 + 跨域共享表
```

工作区构建示例：`python3 -m domimap build <你的Java工作区> --discover -o out/ws-all`。存在变化时目前仍会扫描全部仓库。

## 全部命令

| 命令 | 作用 |
|---|---|
| `python3 -m domimap doctor` | 环境自检（平台/可选依赖/图谱状态） |
| `python3 -m domimap build <仓库/工作区> -o out [--discover] [--jobs 8]` | 建图；`--discover` 自动发现子仓（pom/gradle/.git/package.json）并合并跨仓图，RPC 按接口名称启发式关联 |
| `python3 -m domimap update -o out/ws-all` | 按 manifest 检查变化；全无变化可跳过，存在变化时目前仍全仓扫描 |
| `python3 -m domimap scenario req "需求文本" -g 图` | **场景A 需求识别**：领域分类→词表同义词扩展→服务/接口/表/MQ/文档定位卡+建议路径 |
| `python3 -m domimap scenario trb "症状" -g 图` | **场景B 排障**：全图词法检索→文档摘句与相关节点分类展示；尚未实现独立双路召回 |
| `python3 -m domimap query "文本" -g 图 [--domain 订单域]` | 词法种子+一跳图扩展检索；覆盖率不足时返回无匹配（退出码 3） |
| `python3 -m domimap domain -g 图` | 领域地图（域→服务/表/主题/文档 + 跨域共享表 ⚠） |
| `python3 -m domimap impact <符号> -g 图` | 影响面（反向依赖链） |
| `python3 -m domimap review -g 图 -o out/review` | AMBIGUOUS 边导出 Markdown 待审页；审定结果导入尚未实现 |
| `python3 -m domimap serve -g 图` | **MCP stdio 服务器**（5 工具） |
| `python3 -B -m unittest discover -s tests` | 夹具与工程回归；临时输出自动清理 |

## 已实装

- **7 个 synthesizer**：Spring 路由、MyBatis 桥、Dubbo（跨仓 RPC 按接口名称启发式关联）、RocketMQ、**通用 MQ（@KafkaListener/@RabbitListener/@JmsListener 多主题）**、**JPA（@Entity/@Table/@Column→表列+MAPS_TO）**、跨端连线
- **多仓批量**：自动发现、扫描线程池与全局合并；manifest 支持全无变化跳过，存在变化时仍会扫描全部仓库
- **场景命令**：需求定位卡（领域词表扩展辅助中文检索）/排障卡（全图检索后展示文档摘句与相关节点）
- **MCP 热重载**：graph.json 变更自动重建索引；源码变更检测与自动更新尚未实现
- **图 Schema lite**（`domimap.lite.v1`）：节点和边带 `conf ∈ {EXTRACTED, INFERRED, AMBIGUOUS}` + `prov` 规则来源；版本化证据契约待补齐
- **领域打标**：先验种子（`domimap/seeds.json` 可编辑）+ 一跳投票回挂；跨域共享表检测
- **检索原型**：CJK 1/2/3-gram 内建中文检索（不装 jieba 也能查）；词覆盖率门与强匹配的无匹配提示；返回符号与文件路径，尚未提供完整源码片段和精确引用契约
- **MCP 消费面**：`kg_explore` 主工具 + `kg_domain_map`/`kg_impact`/`kg_doc_search`/`kg_troubleshoot`
- **治理 lite**：coverage.json 记录部分解析失败与可选依赖缺口，AMBIGUOUS 待审导出；完整跳过/截断清单与人审写回待补齐

## 接入 Claude Code / 其他 MCP 客户端

以下为手工配置示例（Claude 的 `~/.claude.json` 或其支持的相应作用域）；各客户端配置格式不同，四客户端联调尚待完成：

```json
{"mcpServers": {"domimap": {
  "command": "python3",
  "args": ["-m", "domimap", "serve", "-g", "/绝对路径/out/你的仓/graph.json"],
  "env": {}
}}}
```

（源码运行：在 domimap 项目根目录下 `python3 -m domimap ...`；pip 安装后直接 `domimap <命令>`，如 `domimap query "订单改价" -g 图`。）

## 可选依赖（按需，不装不影响核心）

```bash
pip3 install jieba          # 中文分词增强（内建 CJK n-gram 已兜底）
pip3 install python-docx    # .docx 文档摄入（本机已装则自动启用）
pip3 install pypdf          # .pdf 文档摄入（本机已装则自动启用）
```

Windows：直接 `py -3 -m domimap ...`（无需 setup.sh）；`.doc` 旧格式先 `soffice --headless --convert-to docx`。

## 项目结构与维护

```text
domimap/       核心实现与领域种子
tests/         回归测试与只读合成夹具
docs/          当前计划、架构、能力说明与历史归档
scripts/       项目维护工具
specs/         产品规格、验收案例、任务与进度
benchmarks/    四竞品协议、评分与严格门槛工具
```

```bash
make test                              # 不在项目内留下测试输出或字节码
make verify                            # 规格结构检查和本地回归；不代表生产完成
make release-check                     # 全部案例与真实竞品结果缺失时必须失败
make clean                             # 清理缓存、构建产物和旧测试输出，保留 out/
python3 -B scripts/clean.py --dry-run   # 预览待清理内容
python3 -B scripts/clean.py --outputs   # 额外删除本地 out/ 图；需要时再执行
```

Windows 可直接执行对应 Python 命令，无需 Make。`bash setup.sh` 仅检查环境与运行测试，不自动安装可选依赖；可用 `PY` 指定解释器。测试布局见[测试说明](tests/README.md)，历史规模与版本记录见[归档](docs/archive/2026-10-16/README-history.md)。

最终质量要求见[比较规格](specs/benchmark.md)：在冻结任务和同条件下，三项指标对四个竞品逐一严格胜出。当前没有真实比较结果，评分器自测不能作为胜出证明。
