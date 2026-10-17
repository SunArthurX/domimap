# comparison-maintrack-runner：主轨运行器骨架（§11.2 任务 3 的主轨半）

来源：计划 §11.2 任务 3（comparison-agent-runner）、§5（预算冻结/记账）。
性质：**评测基础设施骨架**。真实宿主+模型凭据到位后只需注册 HostAdapter 实现；
当前以 DryRunHost（显式标注 synthetic/diagnostic_only，不产生正式证据）锁定管道契约。

## 已锁定契约（测试）

1. **每题全新会话**（session id 唯一，不跨题复用/读他题答案）。
2. **预算硬顶**：工具调用数 / 新增 token / 墙钟任一超限 → 该题终止并记
   budget_exceeded_*（不静默、不删题）。
3. **逐题账本**：tokens_in/out、tool_calls、secs 累计；原始回合转写落盘。
4. 记录含 system/host/model 标识与注册清单（每次只启用一个被测产品）。
5. 问题输入无 gold 字段（复用运行器侧拒收语义）。

## 设计

`benchmarks/runners/main_track.py`：
- `TrackBudget`（wall_clock_s/max_tool_calls/max_new_tokens/max_input/max_output）。
- `HostAdapter` 协议：open_session/close_session/ask（返回回合：answer 文本、工具
  调用数、token 计数、耗时）。真实宿主（claude/codex/zcode/dsh CLI 或 SDK）在此注册。
- `MainTrackRunner.run(system, host, questions, budget)`：编排 + 账本 + 记录
  （schema domimap.maintrack.v1，与诊断轨 QueryRecord 字段兼容 + 账本扩展）。
- `DryRunHost`：确定性伪宿主（synthetic 标注）。

## 回退

单提交回滚；新文件无耦合。

## 边界

- DryRunHost 产物**永不作为正式证据**（schema 带 synthetic:true；评分器侧另行拒绝）。
- 四客户端真实注册（含 domimap MCP 与四竞品原生启用/停用钩子）待凭据后接线。
