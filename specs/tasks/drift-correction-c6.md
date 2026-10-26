# drift-correction-c6 — 入口与原计划验收覆盖补齐（F10）

依据 out/drift-audit-2026-10-26 C6。日期：2026-10-26。案例：AC-R06-03/04（入口共享语义）。

## 新增入口（共用服务，非各做一套）

- MCP `kg_feedback` 工具：按用户明确判定提交反馈（user_feedback 来源，枚举/长度/
  修订号参数校验与 schema 一致；tests/test_feedback.py::test_mcp_feedback_tool）。
- CLI `qsnapshot`/`qrestore`/`qdelete`：备份/安全恢复/受控删除的可用路径（恢复先校验
  后触碰、占用拒绝、固定证据拒绝——C1 语义的入口化）。
- UI `GET /api/event?id=`：记录详情（事件+反馈修订历史+有效判定）；400/404 负例。

## EV01–EV14 → 正式案例/测试映射（本闭环范围内）

| EV | 案例 | 证据（测试） |
|---|---|---|
| EV01 三入口同序 | AC-R06-03 | test_observation 三入口同序 |
| EV02 候选≠hit | AC-R06-04 | test_feedback 人工判定 + stats unknown |
| EV03 正确拒答 | AC-R06-04 | correct_refusal 分母限定 |
| EV04 召回/排序区分 | AC-R06-05 | pool_probe + rank_N |
| EV05 范围如实 | AC-R06-05 | scope_filter 映射（不放宽） |
| EV06 AI 不可用 | AC-R06-05 | unavailable/invalid_response/冷却 |
| EV07 并发反馈 | AC-R06-04 | expected_revision/幂等冲突 |
| EV08 记录库故障 | AC-R06-03 | fail-open + 延迟上界 |
| EV09 注入 | AC-R06-05 | DATA 段数据非指令 + 白名单 |
| EV10 修复致退化 | AC-R06-06 | compare_runs regressions 拒激活 |
| EV11 旧事件不改写 | AC-R06-03 | 追加修订/版本一致性 |
| EV12 删除恢复 | AC-R06-04 | lifecycle 全套 |
| EV13 回放隔离 | AC-R06-04/06 | trigger 分离测试 |
| EV14 能力如实 | AC-R06-05/06 | replayable=false / unavailable / unknown 指纹 |

真实四客户端会话证据仍按 M4 案例独立验收，不在本闭环内冒充完成。

## 验证

python3 -B -m unittest tests.test_feedback tests.test_mcp_desc -v。

## 回滚

revert mcp.py/__main__.py/ui.py 本片差异；test_mcp_desc 工具集还原。

## 文件

domimap/mcp.py、domimap/__main__.py、domimap/ui.py、tests/test_feedback.py、
tests/test_mcp_desc.py、specs/tasks/drift-correction-c6.{json,md}。
