# m0-ci-install：CI 基线、干净安装检查与回放口径拆分

- 关联：R13（可执行防偏离约束）；强化 AC-R13-01（已 verified，本任务增加 CI 级守护并刷新证据）。
- 问题：①回放测试只报"混合命中率"，raw 与 scenario 口径不可分（roadmap M0 明确要求拆分，防止用场景卡兜底掩盖 raw 检索退化）；②无 CI；③分发物未在干净环境异目录验证安装。
- 预期结果：CI（GitHub Actions，ubuntu/macos × 3.11/3.13）跑 make verify + build + 全新 venv 安装 + 异目录 `domimap doctor/build/query` 冒烟，并守护"release-check 在无证据时必须失败"；本地同一脚本可复现。
- 边界：不在 CI 中安装四竞品（M0.2 另行）；不改动产品代码。

## 正例 / 负例

- 正例：`make verify` 中 `[replay] raw Top-5 命中率` 与 `[replay] scenario 口径命中率` 分别独立输出，raw 断言 ≥75%（roadmap 登记基线 6/8，退化即失败）；`bash scripts/install_check.sh` 全绿。
- 负例：CI 若 release-check 意外通过则报错退出（守护门槛关闭状态）。

## 实施

1. tests/test_replay.py：拆分 test_raw_hit_rate / test_scenario_hit_rate（raw 不含场景卡兜底）。
2. scripts/install_check.sh：build → mktemp venv → 装 wheel → 异目录 doctor/build/query 冒烟。
3. .github/workflows/ci.yml：矩阵 2 OS × 2 Python；末步验证 release-check 失败。
4. 本地实跑 install_check.sh 与全部验证；刷新 AC-R13-01/AC-R14-02 证据指纹（源变化后证据保守失效并重跑）。

## 验证与回退

- `make verify`；`bash scripts/install_check.sh`；`check_specs.py --task specs/tasks/m0-ci-install.json --base fb3dac6`；`--stage M0` 通过。
- 回退：删除两个新文件 + revert test_replay.py；无数据迁移。
