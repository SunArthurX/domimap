# m0-competitor-env：四竞品环境核实、健康检查、隔离设计与 tiny dev 五系统回放 spike

- 关联：R14（AC-R14-02 的 M0 部分：比较协议 spike 可执行）；M0 出口的比较准备项。
- 实测（2026-10-16，克隆位于 ~/work/yingta/kb-tools-analysis/repos/）：
  - claude-obsidian 2.2.0：纯 Python 零依赖核心，克隆内直接 import OK，CLI（doctor/transaction/...）OK。
  - graphify（PyPI 名 graphifyy）0.9.91：venv 从克隆安装 OK；tiny 语料（mini 夹具 45 节点）索引+查询真跑通，返回 file:line。
  - codegraph 1.6.2：npm ci 183 包 OK；`codegraph --version` OK；dist 需自建（tsc build 后台进行中）。
  - codebase-memory-mcp：C 单二进制，Makefile.cbm 构建后台进行中；未完成前如实记"未就绪"。
- 交付：benchmarks/env/competitors.md（版本/入口/健康状态/缺口）、benchmarks/DATA_LAYOUT.md（dev/确认隔离设计）、benchmarks/tiny_dev/{questions.json,runner.py}（公共输出映射 + Hit@5 文件级评分 + domimap/graphify 真适配器 + --selfcheck）。
- 判定：五系统全部真跑通 tiny 回放前，M0 保持 implementing；任何系统未就绪都记录"缺什么"而非零分。

- 范围补充（收口）：tests/test_release_gate.py —— M0/M1 置 verified 后原用 M1 做'天然未完成'样本的阶段门测试改用 M5（行为不变，样本更新）；cbm 适配器经实测修正（项目名取 index 返回 slug、默认 full 模式公平性）。
