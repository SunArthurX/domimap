# product-query-discipline：agent 查询构造纪律——原文直查优先 + 引用守门

- 关联：R14（绝对底线收敛——agent-loop 口径当前最大失分点的实测杠杆）、R04（检索质量——
  本任务不改检索本体，只改产品表面与客户端配置）、R05（工具描述是产品表面）。
- 来源：引用纪律假设的 instrumented 诊断（2026-10-22，out/semantic-bridge-ab/
  citation-diagnosis.json，19 个 embed 臂 miss 带工具输出全录重跑）——**假设被推翻**：
  - a) gold 从未出现在任何工具输出：**15/19**（主体）——其中检索级（题面直查+embed）
    可命中 **4/15**（dv2-0060/0096/0120/0122），agent 因**改写查询丢失原文 bigram**
    （"单独对"→"单个作品"）而错过；其余 11/15 检索级也不可达（mock 文档题质问题）。
  - b) 纯引用遗漏：1/19；d) 有据拒答：3/19；c) 幻觉引用：7/19（与 a/d 重叠，多为常识性
    路径如 README/CHANGELOG，非编造细节）。
- **杠杆重定位：引用纪律 → 查询构造纪律**。修复面：①产品表面——kg_explore 工具描述加
  "先用问题原文直查（保留原词面），再按概念改写重试；改写会丢失原文关键 bigram"指引
  （惠及所有 MCP 客户端）；②评测宿主 SYSTEM_PROMPT 同型一句（客户端配置，与四竞品各自
  宿主同权）；③引用守门一句——"引用只用检索结果中出现过的 @ 路径"（压制 7/19 的幻觉引用）。
- 预期（诚实）：可达上限 = 4/15 的 a 类 + 幻觉引用修正的间接收益，单重复噪声带 ±1；
  11/15 的 mock 题质人口不在本任务射程（题质治理独立任务）。

## 正例 / 负例

- 正例：kg_explore 工具描述（domimap/mcp.py 与 benchmarks/runners/glm_host.py 的 TOOLS_SPEC
  同步）含查询指引与引用守门两句；agent 首查使用问题原文。
- 负例：不改检索本体（打分/融合/守门/图语义零变化）；不改题目/gold/评分器/预算
  （R14 反作弊红线）；指引不得暗示 gold 位置或题型；默认路径（无 LLM 的 CLI/UI）零变化。
- 负例：负例题（图外概念）在指引下仍必须能被诚实拒答（拒答守门先于一切）。

## 实施（精确 allowlist）

1. `domimap/mcp.py`：kg_explore 工具 description 增两句（查询指引+引用守门）。
2. `benchmarks/runners/glm_host.py`：TOOLS_SPEC 同步 description；SYSTEM_PROMPT 增同型
  一句（原文直查优先）。
3. `tests/test_mcp_desc.py`（新，hermetic）：描述含指引关键句；serve 冒烟不变；
  工具 schema 不变。
4. agent-loop A/B：embed 臂（已录 17/36）vs discipline 臂（embed+指引，同预算同评分器）；
  如实记录（含零/负效果）。

## 验证与回退

- `python3 -B -m unittest tests.test_mcp_desc -v` 4 契约全绿；refresh_evidence 后
  `make verify` 431/431 全绿（检索本体零改动由存量契约守护）。
- **agent-loop A/B（2026-10-22，40 题三臂同评分器，工件 out/diagnostic-runs/pub-eval-embed/
  {baseline,embed,discipline}/）——纪律臂 +3 净增零回归**：
  - 基线 16/36 → embed 17/36 → **embed+纪律 20/36**；负例 4/4 三臂一致。
  - 相对 embed 臂新增 dv2-0090/0064/0096（0096 正是诊断出的"检索可达但 agent 改写丢词"
    题），**零丢失**；分类别 code 7/8、cross 8/8 保持，doc 1→2、freshness 0→2。
  - instrumented 诊断（citation-diagnosis.json，19 miss 带工具输出全录）：15/19 gold 未经
    工具输出（其中检索级可达 4）、纯引用遗漏 1、有据拒答 3、幻觉引用 7（与上重叠）——
    "引用纪律"假设被推翻，杠杆实为查询构造纪律（原文直查优先）。
- 剩余人口如实：11/15 检索级也不可达（mock 文档题质）——题质治理独立任务；单重复 ±1
  噪声带（20/36 vs 17/36 在带外）。
- 回退：revert 单提交。
