# 第三方来源与清单

## 源码

本仓库当前 **未 vendored 任何第三方源码**。全部核心实现为原创（Python 标准库）。

设计参考了以下项目（只借鉴思想与接口形态，未复制代码、提示词或资源；比较协议见 specs/benchmark.md）：

| 项目 | 许可证（据其仓库声明） | 参考内容 |
|---|---|---|
| AgriciDaniel/claude-obsidian | MIT | 人工知识事务/审批/账本思想 |
| DeusData/codebase-memory-mcp | MIT | 覆盖缺口一等数据、观测与静态分离 |
| colbymchenry/codegraph | MIT | 供给侧单工具面、增量收敛测试范式 |
| Graphify-Labs/graphify | Apache-2.0 | 三级置信、图扩展检索、拒答分级 |

正式复用上述项目代码/提示词/二进制前，须按其版本核对许可与通知要求并在本文件登记。

## 可选运行时依赖（均非核心所需）

| 包 | 许可证 | 用途 |
|---|---|---|
| jieba | MIT | 中文分词增强（未装时内建 CJK n-gram 兜底） |
| python-docx | MIT | .docx 摄入（可选 extras `docs`） |
| pypdf | BSD-3-Clause | .pdf 摄入（可选 extras `docs`） |

## 构建工具链

setuptools（MIT）、build（MIT）、twine（Apache-2.0）——仅开发/发布阶段使用，不随包分发。
