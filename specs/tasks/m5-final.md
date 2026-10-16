# m5-final：终验行为收口（R13-02/R14-01 证据定稿）

- check_release_behavior.py：断言 12/12 成对 + 负例 1.000 已过、当前 gate_reasons 仅绝对底线（评分器如实拒绝）。
- release_gate 测试更新：M5 全 verified 后 stage 检查通过；未知阶段仍拒绝。
