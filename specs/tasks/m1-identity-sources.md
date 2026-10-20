# m1-identity-sources：显式来源身份、字节哈希与 D3/D4 修复

- 关联：R01（AC-R01-01 跨仓/同路径/顺序反转身份不串接）、R08（AC-R08-01 越界链接拒绝或显式登记）。
- 问题：①实体/文档 ID 无仓/类限定，跨仓同 FQN、同路径 README、同类名方法互相合并（D4）；②根内 symlink 指向根外的文件被默读摄入（D3）；③无来源身份层（逻辑身份 vs 路径 vs 内容版本分离，R01 前提）。
- 预期结果：跨仓同 FQN/同路径文档按 (repo, path) 独立成节点；同 service 内跨类同名方法独立成节点且跨类 CALLS 边不再因共点丢失；越界 symlink 被拒绝并记入 coverage（可见不静默）；`SourceRegistry` 提供登记根/来源→sha256 内容版本/可持久化重绑的最小身份层。
- 边界：不做 CLI 接线与 generation 发布（M1.3）、不做重载/字段别名解析（M1.2 只保证"独立且不串接"）。

## 设计要点

- 新 ID 方案：`cls:{repo_or_service}:{fqn}`、`mth:{repo_or_service}:{Class}.{method}`、`doc:{service}:{path}`。service 已含 repo 前缀（多仓）或仓目录名（单仓），故天然跨仓独立；类限定解决 D4。
- `domimap/source.py`：`SourceRegistry.register_root/register`，路径解析越界（含 symlink）抛 `OutOfRootError`；`save/load` 持久化（逻辑 ID 稳定，路径可重绑，M1.3 使用）。
- `lite_scan._walk`：symlink 文件 resolve 后不在根内 → 跳过并记 `coverage.skipped{reason:"越界 symlink 拒绝"}`（纵深防御，与 registry 独立）。
- 既有 golden 测试按新语义更新（同类名共点旧断言是错误语义，理由记录于此；CALLS 契约从 1 条变 2 条——跨类 changePrice→changePrice 边不再丢）。

## 正例 / 负例

- 正例（tests/test_identity.py，先失败后实现）：
  1. 跨仓同 FQN 类/同路径 README：合并扫描后节点两两独立、内容各自正确；
  2. 根顺序反转 [repoA,repoB]/[repoB,repoA]：节点 ID 集合完全一致；
  3. registry save/load：逻辑 ID 稳定，路径重绑后 ID 不变；
  4. 同 service 跨类同名方法：`mth:...:OrderController.changePrice` ≠ `mth:...:OrderPriceService.changePrice`，且 CALLS 跨类边存在（golden 夹具）。
- 负例：根内 symlink 指向外部文件 → 不摄入（图内无外部标记）+ coverage 记录越界拒绝；`SourceRegistry.register` 对根外路径抛 `OutOfRootError`。

## 验证与回退

- `python3 -B -m unittest tests.test_identity tests.test_golden -v`；`make verify` 全绿；task diff 检查 `--base 0fee291`；`scripts/refresh_evidence.py m1-identity-sources 0fee291` 定稿 + 新增 AC-R01-01/AC-R08-01 证据；progress：两案例 verified、M1=implementing。
- 回退：revert 本任务文件即可；新 ID 方案仅影响图内部键，graph.json 旧产物由版本门控自动重建。
