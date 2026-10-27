# release-gate — RV07：正式分发绑定最终验收（pypi workflow）

依据 out/agent-review-2026-10-27/review.md RV07（publish 仅依赖 build）。

## 修复：pypi.yml 由 build+publish 两作业改为 build → verify（同提交 make ci + install_check）→ release-gate（`make release-check` 必须通过；M4/M5/四竞品证据缺失时失败 → 无 release-proof 工件 → publish 无从执行，不绕过 R14）→ publish（只下载 build 产物，核对 sha256 与 release-proof 完全一致后 Trusted Publishing；绝不重新构建）。build 记录逐文件 sha256 进 dist-proof 工件。

## 现状：release-gate 在当前状态**必然失败**（M4 implementing）——这是规范要求的正确行为；正式发布在验收完成前不可达。
