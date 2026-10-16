# m4-forget-corpus：归档越界防护/主动遗忘 + M5 语料清单（M4 收尾）

- R07-03：①restore 拒绝归档内符号链接 kb.db/manifest（防穿越）；②forget(note_id, reason) → 主表删除+tombstone（时间/原因），检索/导出/恢复新建均不见，**遗忘前备份恢复仍含该笔记（效果可解释）**；③purge_expired(retention_days) 清理过期墓碑；④purge 硬删含修订（显式操作）。
- R14 起步：benchmarks/corpus/manifest.py——以 ~/work/dev-corpus 45 仓为独立来源族，dev/confirm 按族隔离分片（20/25），输出冻结清单（族名/分片/文件计数/内容摘要，无正文）。
