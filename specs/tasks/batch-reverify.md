# batch-reverify — 2026-10-24 指纹失效案例的批量重验（漂移纠正二期收尾）

日期：2026-10-26。依据 out/handoff.md「下一具体动作」第 3 项。

## 关联需求与案例

- R13 / AC-R13-01（证据治理：指纹失效后真实重验，不是改哈希）。
- 影响面：42 例 implementing → 预期 34 例重验为 verified、8 例如实保持 implementing。

## 做什么

1. `scripts/publish_scan.sh`：推送/发布前净化扫描（allowlist/生成物/密钥/私有路径），作为 AC-R11-02 的可重复命令。
2. `scripts/reverify_cases.py`：COMMANDS 34 条强化命令（原命令 + T4-T15 新增回归模块；install_check 共享一次运行）逐条实跑，
   exit 0 才写新证据（当前指纹/日志 sha/沿承 limitations + 重验说明）并置 verified（旧证据入 historical_evidence）；
   任一失败则整体退出不提升。PREREGISTERED 两例为 2026-10-26 真实 Claude Code 会话（C1-01 上下文任务 / C1-02 受管生命周期，
   日志在同目录；重放需客户端，refresh_evidence 按 claude 前缀跳过重跑）。
3. 保持 implementing（外部条件未变）：AC-F1-C2-01/02（Codex 账号模型封锁，10-26 探测仍在：gpt-6.1-sol 不支持 ChatGPT 账号）、
   AC-F1-C3-01/02（需用户开新 ZCode 会话）、AC-F1-C4-01/02（DSH 可执行未定位/模型余额）、AC-F3-02（四客户端人设生效）、
   AC-R14-01（dev 包 hit@5=0.644 < 0.80 绝对底线）。

## 验证

`python3 -B scripts/reverify_cases.py`（34 条全绿才提升）→ `python3 -B scripts/refresh_evidence.py batch-reverify f0c7c18`（两遍）→ `make verify`。

## 回滚

见 manifest。
