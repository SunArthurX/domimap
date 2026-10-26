# Spec-driven workflow

日期：2026-10-16。本文件规定执行方式；[产品规格](product.md)与[比较规格](benchmark.md)规定必须交付什么。借鉴 [GitHub Spec Kit](https://github.com/github/spec-kit)的 specify → plan → tasks → implement → converge 思路，使用仓库内普通文件与轻量检查器，不要求所有 Agent 安装同一插件。

## 1. 从真实问题开始

对每个切片先回答：谁在什么输入/状态下遇到什么问题？正确行为是什么？违反它会造成什么损失？这一步是否为现有要求提供必要条件？能否以更小的正确实现达成相同要求？

不能用“别的工具有”“将来可能有用”直接扩大范围，也不能用“小一点容易过测”删掉用户要求。解析器、存储、向量、监听等选择必须服务于正确性/任务收益或已测成本。

## 2. 一个切片的文件

在 `specs/tasks/` 创建同名的 `<task>.md` 和 `<task>.json`。JSON 从 [task-template.json](task-template.json)复制，替换全部占位内容，列出准确文件。`kind` 声明切片类型并受 `check_specs` 全量边界检查：`slice`（默认）只列本片产品/测试/文档文件，不得列规范文件（product/requirements/acceptance/benchmark/workflow/protocol）或其他任务 manifest；`spec-change` 修改登记与需求/验收文本，可列其他 manifest，但不含 `domimap/` 产品代码；`umbrella` 用于跨片全 diff 范围检查，须写 `reason`。Markdown 至少包含：

1. 关联需求与验收 ID；问题、预期用户结果和本切片边界。
2. 前置依赖、输入/输出、状态转移、错误/预算、版本/迁移契约。
3. 设计选择及较简单方案为何不足；新依赖固定版本/许可证/可选性。
4. Given/When/Then 正例、负例、并发/中断或安全反例；gold 从来源位置与必要事实独立标注。
5. 具体文件与有序任务；测试先暴露问题，修复后验证行为。
6. 验证命令、环境、结果工件、回退和遗留缺口。

仅有任务编号或一段抽象架构不能替代输入/输出样例。首个引用/存储/接口契约需给完整可校验示例，再迁移代码。

## 3. 生命周期

`planned → implementing → verified`；外部条件缺失可标 blocked 并注明具体原因。blocked 不代表可以跳过最终交付；可继续其他独立切片。

- **planned**：需求、边界和验收明确，尚无完成证据。
- **implementing**：正在实现或证据未齐。阶段内可以有已验证切片，但阶段整体不提前完成。
- **verified**：当前源指纹、测试/操作成功记录、输出工件与验收一致。

`specs/progress.json` 逐案例登记；阶段状态是汇总，不能先勾阶段再补证据。无证据的“已完成”由检查器拒绝。M4 依赖 M2，可与 M3 独立推进；M5 同时依赖 M3/M4。早期先验证结构，最终才要求全量产品与竞品结果。

## 4. 可执行检查

```bash
make spec-check
make verify
python3 -B scripts/check_specs.py --task specs/tasks/<task>.json --base <local-git-ref>
python3 -B scripts/check_specs.py --stage M2
make release-check
```

前两条用于日常结构/测试/文档检查，不输出“产品完成”。task 模式检查实际 Git 变更是否超出允许文件，并拒绝未知需求/验收/缺失规格；没有 Git 时先完成 M0 的版本管理，不能假装检查过 diff。stage 模式验证依赖与该阶段全部案例证据。release 模式要求 M0–M5 全 verified、全部案例证据有效，再计算真实比较包的最终门槛。

已知原型缺陷要用失败诊断展示；对应契约修复后成为正常回归。不能长期把生产失败标 skip/xfail 而报告通过；临时诊断和正式发布检查分别列状态。

## 5. 验收证据格式

progress 中的 evidence 指向项目内 JSON 文件，建议放 `out/verification/`；确认后的净化报告可另存为发布工件。证据至少包含：

```json
{
  "schema_version": 1,
  "case_id": "AC-R01-01",
  "outcome": "pass",
  "source_fingerprint": "<check_specs.source_fingerprint 生成的 SHA-256>",
  "command": ["python3", "-B", "-m", "unittest", "..."],
  "exit_code": 0,
  "environment": {"os": "...", "python": "..."},
  "artifacts": [{"path": "out/verification/result.log", "sha256": "<hash>"}],
  "limitations": []
}
```

指纹覆盖核心、测试、工具、基准配置与活动规格/文档；排除 progress、运行输出和历史归档。相关源变化后保守失效，重新执行受影响/必需验证并更新证据；不是把旧哈希改成新哈希。

客户端真实会话、UI、平台、长运行、恢复等案例也使用相同封装，command 可记录实际运行器/操作脚本，日志/截图/导出清单保留哈希。测试通过本身不证明日志中的断言有意义，维护者仍需检查其与 Given/When/Then 的对应。

检查器验证结构、完整性、指纹与路径，**不能证明人审独立性、运行记录未伪造或某段测试确实覆盖语义**。独立 CI、冻结输入、原始记录与人工复核是另外的信任条件，不以一个 JSON pass 字段替代。

## 6. 变更与不走偏约束

- 接口、状态、身份、定位或持久格式变化先更新任务规格/版本/迁移和验收，再写依赖代码。
- 新文件必须属于任务；发现确有必要的额外文件时先补任务说明，不能借机会重写无关模块。
- 调整算法可用 dev 集；保留 raw/scenario/扩展项界限，禁止用更大隐藏预算提升自己的指标。
- 不新增一套临时知识格式，不让 UI/MCP 绕开公共服务，不让副本、人设或时间权重制造事实。
- 第一条可用路径尽早测：来源 → 可读证据 → 查询；在此上做保存/复核。功能完整性最终由所有需求判断，不以这条小路径替代全部目标。
- 外部阻塞记录“缺什么、影响哪些案例、已验证什么、可继续什么”；不要为读取/普通本地修复反复求确认。

## 7. 自测与交接

每次切片按顺序完成：相关单元/契约 → 必要集成/负例 → 全部本地回归 → 来源/工件检查 → 本切片案例收敛。出现新失败先定位原因，不扩大运行次数来碰到一次绿灯。

在 `out/handoff.md` 记录源指纹/提交、已完成案例、执行过的命令与结果、待办/阻塞、下一具体任务；不保存秘密、原始业务查询或受限正文。换 Agent 先读规格、progress、handoff，再核对当前代码；历史对话不能覆盖真实状态。

最终完成需要生产硬门槛、支持矩阵、全量案例、真实竞争门槛同时成立。缺任一项就报告具体未完成项，不用“已做自测”泛化为交付成功。
