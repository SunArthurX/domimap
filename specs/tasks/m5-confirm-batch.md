# m5-confirm-batch：confirm 问题集+机械 gold（M5.1，AC-R14-01 前置）

- 已建：generate_questions.py——302→399 可回答 + 110 不可回答，24 confirm 族，gold 从**原始文件 grep/mtime 机械派生**（不经 domimap 管线），输出仓库外 ~/work/dm-benchmark/questions.json。
- 试点（非正式）：管线验证 40 题，domimap hit@5=19/30、负例拒答 9/10、18s（out/verification/m5-pilot.json）。
- **正式门槛阻塞（如实）**：①document_reasoning 类 28<50——confirm 族文档稀疏是语料事实，需扩语料（增文档丰富族）或用户批准协议变更（不得自行放宽）；②正式须 confirm-only 索引（当前混图）+ canonical 路径映射；③事实级 gold 与独立盲化裁决（AC-R14-01 全量要求）未建；④五种子×五系统全量运行待算力。
