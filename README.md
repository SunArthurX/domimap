# domimap — 多仓知识库检索引擎

**Domain + Map**：把多个 Java 仓库、项目文档和人工知识变成一张可查询的领域地图。

[![CI](https://github.com/SunArthurX/domimap/actions/workflows/ci.yml/badge.svg)](https://github.com/SunArthurX/domimap/actions/workflows/ci.yml) [![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://github.com/SunArthurX/domimap/blob/main/pyproject.toml) [![Dependencies](https://img.shields.io/badge/deps-zero%20core-success)](https://github.com/SunArthurX/domimap/blob/main/pyproject.toml) [![License](https://img.shields.io/badge/license-MIT-lightgrey)](https://github.com/SunArthurX/domimap/blob/main/LICENSE)

---

## What is domimap? / 什么是 domimap？

**English**: domimap is a local-first knowledge retrieval engine that builds a queryable domain map from multiple Java repositories, project documentation, and human-curated knowledge. It provides CLI, MCP (Model Context Protocol) server, and web UI interfaces — enabling both humans and AI agents to search, trace, and cite evidence across your entire codebase.

**中文**：domimap 是一个本地优先的知识检索引擎，把多个 Java 仓库、项目文档和人工知识构建成一张可查询的领域地图。提供 CLI、MCP 服务器和 Web UI 三种接口——让人和 AI Agent 都能在整个代码库中搜索、追踪和引用证据。

## Key Features / 核心能力

| Feature | Description | 说明 |
|---|---|---|
| **Multi-repo aggregation** | Index multiple repos into one unified graph | 多仓聚合索引为统一图 |
| **Hybrid retrieval** | BM25 lexical + graph expansion + domain seeds | BM25 词法 + 图扩展 + 领域种子 |
| **Evidence citation** | Every result includes file path + evidence ID | 每条结果带文件路径和证据 ID |
| **Immutable evidence** | Source code changes don't break old citations | 源码修改不破坏旧引用 |
| **Knowledge timeline** | Content-era extraction (not file mtime) | 内容纪元提取（非文件时间） |
| **MCP integration** | Native Model Context Protocol server | 原生 MCP 服务器 |
| **Zero core dependencies** | Pure Python stdlib; optional deps enhance | 核心零依赖；可选依赖增强 |

## Quick Start / 快速开始

### Install / 安装

```bash
# Clone / 克隆
git clone https://github.com/SunArthurX/domimap.git && cd domimap

# No install needed — pure stdlib / 无需安装——纯标准库
python3 -m domimap build ~/my-java-projects -o out/my-idx

# Or install as a CLI / 或安装为命令行工具
pip install .            # provides the `domimap` command

# With optional PDF/DOCX support / 可选 PDF/DOCX 支持
pip install pypdf python-docx
```

### CLI Usage / 命令行

```bash
# Build index from multiple repos / 多仓建索引
python3 -m domimap build ~/work/repo-a ~/work/repo-b -o out/idx

# Search (Chinese & English) / 检索（中英文）
python3 -m domimap query "订单改价 changePrice" -g out/idx/graph.json
python3 -m domimap query "ai_resource 表 定义 写入" -g out/idx/graph.json

# Read evidence by ID / 按证据 ID 读固化片段
python3 -m domimap read <evidence_id> --store out/idx

# Impact analysis / 影响面分析
python3 -m domimap impact "OrderService" -g out/idx/graph.json

# Web UI / 交互界面
python3 -m domimap ui --port 8080
```

### MCP Server / MCP 服务器

```bash
# Start MCP stdio server / 启动 MCP stdio 服务器
python3 -m domimap serve -g out/idx/graph.json
```

**Claude Code** / **ZCode** / **Codex** / **DSH** 连接：

```json
{
  "mcpServers": {
    "domimap": {
      "command": "python3",
      "args": ["-m", "domimap", "serve", "-g", "/path/to/out/idx/graph.json"]
    }
  }
}
```

### MCP Tools / MCP 工具

| Tool | Description |
|---|---|
| `kg_explore` | Main search: lexical seeds + graph expansion, returns services/classes/methods/routes/tables/docs with confidence and provenance |
| `kg_read` | Read evidence by ID (immutable — survives source changes) |
| `kg_domain_map` | Domain map: domain → services/tables/topics/docs |
| `kg_impact` | Impact analysis: reverse dependencies of a symbol |
| `kg_doc_search` | Full-text document search |

## Architecture / 架构

```
┌─────────────────────────────────────────────────────┐
│                  Interfaces                         │
│  CLI ─── MCP Server ─── Web UI ─── JSON API        │
├─────────────────────────────────────────────────────┤
│               Search Engine                         │
│  BM25 (k=1.2, b=0.75) + Identifier Boost           │
│  + Graph Expansion + Domain Seeds                   │
│  + Negative Refusal Guards + Doc Lane Merge         │
├─────────────────────────────────────────────────────┤
│              Knowledge Graph                        │
│  231K nodes / 1.16M edges (9-repo test)            │
│  Classes · Methods · Tables · Routes · MQ · Docs    │
├─────────────────────────────────────────────────────┤
│           Evidence Store (SQLite)                   │
│  Content-addressed · Immutable generations          │
│  SHA-256 blobs · Source versioning                  │
├─────────────────────────────────────────────────────┤
│         Knowledge Base (SQLite)                     │
│  Human notes · Claims · Review workflow             │
│  Dependency invalidation · Export/Restore           │
├─────────────────────────────────────────────────────┤
│           Scanners                                 │
│  Java (GBK/UTF-8) · XML (MyBatis) · SQL (DDL)      │
│  Markdown · HTML · PDF* · DOCX* · TS/JS/Vue         │
└─────────────────────────────────────────────────────┘
  * = optional dependency required
```

## Benchmark Results / 基准测试结果

Five systems — domimap and four open-source competitors ([Codebase-Memory-MCP](https://github.com/DeusData/codebase-memory-mcp), [claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian), [Graphify](https://github.com/Graphify-Labs/graphify), [CodeGraph](https://github.com/colbymchenry/codegraph)) — were driven by the **same host model (GLM-5.3), the same system prompt, the same turn/tool budget, and a per-system copy of the same workspace**. Scoring is mechanical answer-layer citation matching (bidirectional path match). All numbers below are **same-session developer evaluations, not the frozen independent confirmation run** required by [specs/benchmark.md](specs/benchmark.md); the release gate (`make release-check`) therefore stays closed.

五系统（domimap + 四个开源竞品）使用**同一宿主模型 GLM-5.3、同一系统提示、同一轮次/工具预算、同一语料的独立工作区副本**；评分为机械的答案层引用匹配（双向路径匹配）。以下数字均为**同会话开发者评测，不是 [specs/benchmark.md](specs/benchmark.md) 要求的冻结独立确认**，因此发布门禁 `make release-check` 仍处于关闭状态。

### Dev set — enterprise Java corpus / 开发集（企业 Java 多仓语料）

33 questions: 27 scored positives (code 8 · cross-repo 8 · doc 5 · fresh 6) + 4 negatives + 2 locator-diagnostic.
33 题：27 道计分正例（代码定位 8 · 跨仓追踪 8 · 文档推理 5 · 知识时效 6）+ 4 道负例 + 2 道定位诊断。

| System | code | cross-repo | doc | fresh | **Positives** | Negatives (abstain) | Locator |
|---|---|---|---|---|---|---|---|
| **domimap** | **8/8** | **8/8** | **4/5** | **4/6** | **24/27 (89%)** | 4/4 | 2/2 |
| Codebase-Memory-MCP | 0/8 | 8/8 | 0/5 | 1/6 | 9/27 (33%) | 4/4 | 0/2 |
| CodeGraph | 3/8 | 0/8 | 0/5 | 0/6 | 3/27 (11%) | 4/4 | 0/2 |
| Graphify | 2/8 | 0/8 | 0/5 | 0/6 | 2/27 (7%) | 4/4 | 1/2 |
| claude-obsidian | 0/8 | 0/8 | 0/5 | 1/6 | 1/27 (4%) | 4/4 | 1/2 |

### Public corpus — 27 unseen open-source families / 公开语料（27 个未暴露的开源项目族）

40 questions: 32 scored positives (8 per category) + 4 negatives + 4 locator-diagnostic.
40 题：32 道计分正例（每类 8 道）+ 4 道负例 + 4 道定位诊断。

| System | code | cross-repo | doc | fresh | **Positives** | Negatives (abstain) | Locator |
|---|---|---|---|---|---|---|---|
| **domimap** | **6/8** | **8/8** | 4/8 | **4/8** | **22/32 (69%)** | 4/4 | 1/4 |
| Codebase-Memory-MCP | 5/8 | 8/8 | 3/8 | 1/8 | 17/32 (53%) | 4/4 | 2/4 |
| claude-obsidian | 5/8 | 3/8 | 4/8 | 1/8 | 13/32 (41%) | 4/4 | 3/4 |
| Graphify | 3/8 | 0/8 | **5/8** | 3/8 | 11/32 (34%) | 4/4 | 3/4 |
| CodeGraph | 2/8 | 3/8 | 0/8 | 0/8 | 5/32 (16%) | 4/4 | 0/4 |

Paired differences on the public corpus (n = 36 = 32 positives + 4 negatives) / 公开语料配对差值：

| Comparison | domimap | Competitor | Difference |
|---|---|---|---|
| vs Codebase-Memory-MCP | 26/36 | 21/36 | +13.9 pp |
| vs claude-obsidian | 26/36 | 17/36 | +25.0 pp |
| vs Graphify | 26/36 | 15/36 | +30.6 pp |
| vs CodeGraph | 26/36 | 9/36 | +47.2 pp |

All four paired differences are positive on both corpora, but the gaps narrow sharply on the English-heavy public corpus: Graphify leads on document reasoning there, and three competitors beat domimap on the locator-diagnostic subset. These results are scoped to these two corpora and this host and are not a claim of general superiority. Raw result artifacts, runners and the frozen protocol live under [`benchmarks/`](benchmarks/README.md).

四组配对差值在两套语料上均为正，但在以英文为主的公开语料上差距明显收窄：Graphify 在文档推理类领先，定位诊断子集上有三个竞品高于 domimap。结论仅限于这两套语料与该宿主，不构成普适优越性声明。原始结果工件、运行器与冻结协议见 [`benchmarks/`](benchmarks/README.md)。

### Performance / 性能

| Metric | Value |
|---|---|
| Index build (9 repos, 37K files) | 14 minutes |
| Query latency (single query) | < 1 second |
| Full 33-question evaluation | 1.2 seconds (diagnostic track) |
| Memory (peak RSS, 9-repo index) | ~4.3 GB |

## Supported Formats / 支持格式

| Format | Status | Notes |
|---|---|---|
| Java (.java) | ✅ Full | GBK/UTF-8 auto-detect, comments indexed |
| MyBatis XML (.xml) | ✅ Full | Mapper namespace, SQL statements, table extraction |
| SQL DDL (.sql) | ✅ Full | CREATE TABLE parsing, DDL semantic boost |
| Markdown (.md) | ✅ Full | Front-matter (valid_until/superseded_by) |
| HTML (.html) | ✅ Full | Tag stripping, entity decoding |
| Plain text (.txt) | ✅ Full | GBK fallback |
| PDF (.pdf) | ⚠️ Optional | Requires `pypdf` |
| DOCX (.docx) | ⚠️ Optional | Requires `python-docx` |
| TypeScript/JavaScript | ✅ Basic | Frontend framework detection |
| Vue (.vue) | ✅ Basic | Component scanning |

## Development / 开发

```bash
# What CI runs: structural spec check + full test suite / CI 执行的内容：规格结构校验 + 全部测试
make ci

# Local gate: additionally verifies evidence fingerprints and artifact hashes under out/verification
# 本地门禁：额外校验 out/verification 下的证据指纹与工件哈希（verified 状态只由此确认）
make verify

# Release gate — must keep failing until the frozen confirmation run exists
# 发布门禁——冻结确认跑完成前必须保持失败
make release-check

# Build a mini test graph / 构建迷你测试图
make mini
```

Optional parsers for the PDF/DOCX ingestion contracts: `pip install pypdf python-docx` (those tests skip when the parsers are absent).
PDF/DOCX 摄入契约测试需要可选解析器：`pip install pypdf python-docx`（缺失时自动跳过）。

### Project Structure / 项目结构

```
domimap/
├── domimap/           # Core Python package
│   ├── lite_scan.py   # Multi-format scanner
│   ├── graph.py       # Knowledge graph builder
│   ├── search.py      # BM25 + graph search engine
│   ├── mcp.py         # MCP stdio server
│   ├── store.py       # Evidence store (SQLite)
│   ├── knowledge.py   # Knowledge base (SQLite)
│   ├── source.py      # Source registry
│   ├── batch.py       # Multi-repo batch builder
│   └── tokenize.py    # CJK/Latin tokenizer with EN bridge
├── benchmarks/        # Benchmark suite
│   ├── adapters/      # Five-system comparison adapters
│   ├── runners/       # Diagnostic + main-track runners
│   └── corpus/        # Question generators
├── tests/             # Contract tests (every feature has negative cases)
├── specs/             # Requirements, acceptance cases, task manifests
└── docs/              # Documentation
```

## Documentation / 文档

| Document | Description |
|---|---|
| [docs/README.md](docs/README.md) | Documentation index |
| [docs/roadmap.md](docs/roadmap.md) | Production roadmap |
| [docs/architecture.md](docs/architecture.md) | Architecture details |
| [docs/capabilities.md](docs/capabilities.md) | Capability matrix |
| [docs/clients.md](docs/clients.md) | Four-client integration guide |
| [docs/known-defects.md](docs/known-defects.md) | Known defects registry |
| [specs/benchmark.md](specs/benchmark.md) | Benchmark protocol |

## Known Limitations / 已知限制

- **Cross-lingual retrieval**: BM25 cannot semantically match Chinese queries to English document content (22/32 on the English-heavy public corpus vs 24/27 on the Chinese enterprise dev set)
- **Evaluation status**: all benchmark numbers are same-session developer evaluations; the frozen independent confirmation run (`specs/benchmark.md`) has not been executed and `make release-check` fails by design until it is
- **Same-name methods**: Methods with identical names in different classes share a node (service-level naming)
- **Source updates**: Incremental updates require re-running `build` (no file watcher)
- **Platform**: Fully tested on macOS; Linux/Windows expected to work but less tested

## License / 许可证

MIT License. See [LICENSE](LICENSE) for details.

---

## 附录：测试体系 / Appendix: Test Infrastructure

| Layer | Scope | Description |
|---|---|---|
| Unit/contract tests | `tests/` | Every feature has contract tests with negative cases; `make ci` runs them all |
| Diagnostic track | `benchmarks/runners/diagnostic_runner.py` | Five-system path-level retrieval comparison (dev + public corpora) |
| Main track | `benchmarks/runners/main_track.py` | Five-system answer-layer comparison on the shared GLM-5.3 host (33 dev + 40 public questions) |
| Governance | `specs/`, `scripts/check_specs.py` | Task manifests, source fingerprints, hashed evidence chains, release gate |

**Test coverage philosophy**: Every bounded change follows spec → contract tests → negative cases → implementation → regression → evidence → convergence. No checkbox without evidence.
