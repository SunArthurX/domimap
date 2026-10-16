# 四竞品环境调查（M0.2 实测）

日期：2026-10-16。克隆位置：`~/work/yingta/kb-tools-analysis/repos/`（无 .git 元数据，版本取自包清单）。健康检查全部为本机实跑，非宣称。

| 系统 | 版本证据 | 入口 | 健康检查实测 | 状态 |
|---|---|---|---|---|
| claude-obsidian | `claude_obsidian.__version__ == 2.2.0`（克隆内 import OK） | `python3 -m claude_obsidian`（doctor/transaction/capture…）+ 15 Skill（vault 工作流） | import OK；CLI help OK | **可运行**；检索适配器经其核心（BM25+CJK，检索代码在 core/transaction 体系内），M2 dev 适配时接线 |
| graphify | pyproject `graphifyy 0.9.91` | venv `pip install <克隆>` → `graphify` CLI | venv 安装 OK；tiny 语料（domimap mini 夹具）`graphify update .` 建图 45 节点；`graphify query "price_version"` 返回子图（file:line） | **全链路真跑通** |
| codegraph | package.json `@colbymchenry/codegraph 1.6.2` | `dist/bin/codegraph.js`（需先 `npm run build`：tsc+assets+ui） | `npm ci` 183 包 OK；`--version` 1.6.2 OK；dist 构建中 | **安装中**（构建完成后补 init/index/explore tiny 实跑记录） |
| codebase-memory-mcp | Makefile.cbm（C 单二进制工程，1.7G 含 vendored 语法） | `make -f Makefile.cbm build/c/codebase-memory-mcp`（scripts/build.sh 同义） | 正确目标确认（此前误用无 /c 路径）；C 编译后台进行中 | **构建中**（未完成前比较判"未就绪"，不给零分） |

## 公平性要点（对齐 specs/benchmark.md）

- 各系统用原生工作流（graphify=CLI 建图+query；codegraph=init/index/explore；claude-obsidian=vault 摄入+wiki-query；cbm=index_repository+search_graph），同语料、同问题、同预算口径；接口不支持 seed 的记录限制并五次同条件运行。
- 不以"未就绪"给竞品零分：正式比较缺失即"比较未完成"。
- 版本冻结：正式批次前记录各系统精确版本/提交与依赖清单（克隆无 .git，用包清单版本 + 目录内容哈希代存档）。
