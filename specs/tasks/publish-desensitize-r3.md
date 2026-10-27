# publish-desensitize-r3：第三轮去敏感（并行会话提交带回的公司名/个人路径清除）

- 关联：R11（AC-R11-02：待公开源码/历史/日志/附件/构建物净化）；R13（AC-R13-01）。
- 来源：用户 2026-10-27 指示"去除敏感之后提交到 GitHub"。全面扫描发现并行会话 2026-10-24~27 的约 22 个提交带回了四类内容：`out/dev-ws` 路径 ×20、"真实企业工作区" ×2、内部文档标题《商品主数据融合项目设计文档》×4、`scripts/publish_scan.sh` 检查正则内嵌 `/Users/<个人用户名>/work/(dev-corp|dm-corpus)`。

## 正例 / 负例

- 正例：树内替换后全仓 `git grep` 公司名/个人用户名/内部文档标题 = 0（PNG 二进制巧合除外）；本地工件目录同步改名 `out/dev-ws → out/dev-ws`，`out/verification` 证据命令同步修正后 rerun 可过。
- 正例：publish_scan 的家目录检查改为通用模式 `/Users/<user>/(work|Downloads|Documents)/`——不再内嵌具体用户名与语料名，且覆盖面更宽。
- 负例：任何新提交差异中出现本机家目录绝对路径 → publish_scan 告警（延续既有守卫）。

## 实施

1. 树内替换：`out/dev-ws→out/dev-ws`（CHANGELOG/6 个任务 md/reverify_cases/test_drift_correction/test_identifier_ranking）、`真实企业工作区→真实企业工作区`、`商品主数据融合项目设计文档→商品主数据融合项目设计文档`（去 POP 前缀）。
2. `scripts/publish_scan.sh` 第 34 行：内嵌个人路径的专用正则 → 通用家目录模式。
3. 本地配套：`mv out/dev-ws out/dev-ws`；`out/verification/AC-R06-06/07.json` 命令路径修正（证据不入库）。
4. 历史清除：filter-repo 第三轮 replace-text/replace-message（规则见提交 B），重写后全对象流扫描零残留；重写前完整备份 `out/pre-publish-backup-3.bundle`；随后 `--force-with-lease` 推送（敏感移除的正当 force-push 场景，所有会话共用同一工作副本不受影响）。

## 验证与回退

- `python3 -B -m unittest tests.test_drift_correction tests.test_identifier_ranking`；refresh_evidence 后 `make verify` 全绿；新克隆干净环境 `make ci`；全对象流敏感扫描 = 0。
- 回退：树内变更 revert 即可；历史重写以 bundle-3 为准可恢复。
