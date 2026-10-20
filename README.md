# domimap — 多仓知识库检索引擎

**Domain + Map**：把多个 Java 仓库、项目文档和人工知识变成一张可查询的领域地图。

[![Tests](https://img.shields.io/badge/tests-350%2F350-brightgreen)]() [![Python](https://img.shields.io/badge/python-3.9%2B-blue)]() [![Dependencies](https://img.shields.io/badge/deps-zero%20core-success)]() [![License](https://img.shields.io/badge/license-MIT-lightgrey)]()

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
git clone <repo-url> && cd domimap

# No install needed — pure stdlib / 无需安装——纯标准库
python3 domimap build ~/my-java-projects -o out/my-idx

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

### Five-System Comparison / 五系统对比

Tested against 4 open-source competitors with same host (GLM-5.3), same prompt, same budget:

| System | Positives¹ | code | cross-repo | doc | fresh | Negatives² |
|---|---|---|---|---|---|---|
| **domimap** | **89%** | **8/8** | **8/8** | 4/5 | 4/6 | **100%** |
| Codebase-Memory-MCP | 33% | 0/8 | 8/8 | 0/5 | 1/6 | 100% |
| claude-obsidian | 41% | 5/8 | 3/8 | 4/8 | 1/8 | 100% |
| Graphify | 34% | 3/8 | 0/8 | 5/8 | 3/8 | 100% |
| CodeGraph | 16% | 2/8 | 3/8 | 0/8 | 0/8 | 100% |

¹ Answer-layer citation hit on 27-question clean dev set (dev-corp enterprise Java corpus)
² Negative questions correctly abstained (4-question subset)

### Paired Differences / 配对差值

| Comparison | domimap | Competitor | Difference |
|---|---|---|---|
| vs Codebase-Memory-MCP | 26/36 | 21/36 | **+13.9pp** |
| vs claude-obsidian | 26/36 | 17/36 | **+25.0pp** |
| vs Graphify | 26/36 | 15/36 | **+30.6pp** |
| vs CodeGraph | 26/36 | 9/36 | **+47.2pp** |

All four paired differences > 0. domimap leads every category except document reasoning on English corpora.

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
# Run all tests (350 tests) / 运行全部测试
make verify

# Release check / 发布检查
make release-check

# Build a mini test graph / 构建迷你测试图
make mini
```

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
├── tests/             # 350 contract tests
├── specs/             # Requirements & acceptance cases
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

- **Cross-lingual retrieval**: BM25 cannot semantically match Chinese queries to English document content (69% on English corpus vs 89% on Chinese corpus)
- **Same-name methods**: Methods with identical names in different classes share a node (service-level naming)
- **Source updates**: Incremental updates require re-running `build` (no file watcher)
- **Platform**: Fully tested on macOS; Linux/Windows expected to work but less tested

## License / 许可证

MIT License. See [LICENSE](LICENSE) for details.

---

## 附录：测试体系 / Appendix: Test Infrastructure

| Layer | Count | Description |
|---|---|---|
| Unit/contract tests | 350 | Every feature has contract tests with negative cases |
| Diagnostic track | 200+ | Five-system path-level retrieval comparison |
| Main track | 200+ | Five-system answer-layer comparison with GLM-5.3 |
| Governance | Built-in | Task specs, manifests, source fingerprints, evidence chains |

**Test coverage philosophy**: Every bounded change follows spec → contract tests → negative cases → implementation → regression → evidence → convergence. No checkbox without evidence.
