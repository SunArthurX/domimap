# publish-openprep：公开发布前的工程卫生（CI 可运行、凭据细节出库、基准表口径统一）

- 关联：R13（可执行防偏离约束，AC-R13-01：CI/检查器守护）；F1-C3（ZCode 侧主轨凭据纪律，AC-F1-C3-01）。
- 来源：用户 2026-10-20 要求整理仓库并以生产级标准推送到 GitHub 公开仓库。
- 问题（发布前实测）：
  1. CI 从未真正运行（无远端）；在新克隆里 `make verify` 必然失败——`check_specs.py validate()` 无条件读取 `out/verification/*.json`，而 `out/` 不入库。
  2. `benchmarks/runners/glm_host.py` 与 `specs/tasks/comparison-glm-host.md` 含用户本机凭据库的解密方案描述与账号标识，不得出现在公开代码中。
  3. README 五系统表把开发集（27 正例）与公开语料（32 正例）两套数字混排，分母不一致；"配对差值"表未标注数据集。
  4. `tests/test_m4_formats.py` 在缺 pypdf/python-docx 时报 ERROR 而非 skip；`tests/test_release_gate.py` 的"指名未完成案例"断言依赖本地证据。
- 边界：不改产品代码（`domimap/`）；不改 gold/分母/预算/指标；`make verify` 与 `make release-check` 的语义不变。

## 正例 / 负例

- 正例：新克隆 + 干净 venv 中 `make ci` 全绿（结构校验 + 全部测试）；`check_specs.py --structural` 输出 `scope=spec_structure_only, evidence_verified=false` 并在 stderr 明示"verified 状态未确认"。
- 正例：`load_api_key()` 按 `GLM_API_KEY`/`ANTHROPIC_API_KEY` → `DOMIMAP_KEY_HELPER` 本机 helper 顺序取 key；本机 helper（仓库外）保持原有主轨链路可用。
- 负例：默认模式下证据文件缺失必须失败（OSError），结构模式下 `verified` 仍不得无证据声明、证据路径不得逃逸、未知状态仍报错；`--structural` 与 `--stage/--release` 组合必须拒绝。
- 负例：`glm_host.py` 源码中不得出现凭据库文件名、解密方案关键词、AESGCM、长数字账号标识（契约测试锁定）。

## 实施

1. `scripts/check_specs.py`：`validate(require_evidence=True)`；`--structural` 仅跳过证据文件校验，其余结构规则不变；禁止与 `--stage/--release` 组合；summary 增 `evidence_verified`。
2. `Makefile`：`spec-check-structural`、`ci` 目标；`verify` 不变。`.github/workflows/ci.yml`：改跑 `make ci`、安装 PDF/DOCX 可选解析器、`permissions: contents: read`、并发取消、超时。
3. `benchmarks/runners/glm_host.py`：`load_api_key()` 改为环境变量 / 本机 helper；移除解密实现与账号标识；`specs/tasks/comparison-glm-host.md` 同步脱敏。helper 迁至 `~/work/dm-benchmark/zcode_key_helper.py`（仓库外，0600）。
4. `tests/`：`test_spec_contracts.py` 结构模式正负契约；`test_glm_host.py` 加载顺序 + 源码守卫；`test_m4_formats.py` 缺可选依赖整类 skip；`test_release_gate.py` 无本地证据时仅跳过"指名案例"断言，拒绝行为仍断言。
5. `README.md`：真实 clone URL 与 CI 徽章；基准结果按数据集分为两张表（分母一致、含定位诊断列、标注"同会话评测非独立确认"）；Development 节区分 `make ci` / `make verify` / `make release-check`。`CHANGELOG.md` / `CONTRIBUTING.md` 同步。
6. 历史整理（仓库操作，非产品行为）：`git filter-repo` 把全部提交作者/提交者改为 GitHub noreply 邮箱，并对历史 blob/提交信息中的凭据库关键词与账号标识打码；随后按 commit-map 更新 `docs/benchmark-evidence-audit.md` 与 7 个 `specs/tasks/*.md` 里引用的提交哈希。

## 验证与回退

- `python3 -B scripts/refresh_evidence.py publish-openprep <base>`；`make verify` 全绿；新克隆 + 干净 venv（py3.9 / py3.13，含/不含可选解析器）`make ci` 全绿；`bash scripts/install_check.sh` 通过；`make release-check` 仍按预期失败。
- 回退：revert 本任务提交；helper 回迁即可恢复旧的加载方式（不建议）。历史重写前有本地 bundle 备份（`out/pre-publish-backup.bundle`）。
