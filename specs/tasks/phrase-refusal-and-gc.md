# phrase-refusal-and-gc — 长词整段拒答，旧代可清理

日期：2026-10-28。对应计划 T18 和 T21。

## 问题

开发集四道 abstain 题都是「一段没出现过的业务长词 + 规则/配置」。二字散落在别的文档里时，通用词守门不触发，检索返回弱候选。另外 generation 只增不删，历史代文件和无人引用的 blob 一直占磁盘。

## 预期

- 查询里长度 ≥6 的连续中文，其每个四字切片都要在图正文里出现过；一段都不满足则拒答，原因 `phrase_absent`。
- 拉丁标识符是否存在改为检查全部节点，不再只看前 20 万个。
- `EvidenceStore.prune_generations(keep)` 删除更旧的代文件，留下最新 keep 代和 active。
- `prune_unreferenced_blobs` 只删证据表和来源表都没引用的 blob。
- `domimap gc -o <工作区>` 依次做这两件事。

## 负例

- 正文里有整段长词时，不因 `phrase_absent` 拒答。
- 已登记证据的 blob 在 gc 之后仍可读。

## 回滚

去掉长词守门和 gc 命令。已删除的代文件不能从这条命令恢复。
