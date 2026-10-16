# m5-formal-runs：事实 gold + 五系统正式冻结运行（M5.2，进行中）

- 事实级 gold 已生成（外部 ~/work/dm-benchmark/fact-gold.json：489 可回答含语句+源路径（75 含行号）/110 不可回答）——**机械草稿，独立盲化裁决未执行**（正式门槛阻塞，不虚称）。
- 正式运行：domimap 已完成（confirm-only、确定性单次、89s）——DEV 级初评 Hit@5=328/489=67.1%、负例拒答 103/110。分类：cross_repo 95%/code_location 74%/document 60%/**knowledge_freshness 6%（首要差距）**。
- cbm 后台运行中；graphify/codegraph 待跑；claude-obsidian 接口边界（正式五系统不齐，R14 门槛保持开启）。
