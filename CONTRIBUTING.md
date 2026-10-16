# 贡献指南

感谢参与 domimap。贡献前请先阅读：

1. [AGENTS.md](AGENTS.md) — 仓库级开发约束。
2. [specs/workflow.md](specs/workflow.md) — 切片工作流：spec → 失败案例 → 实现 → 证据 → 收敛。
3. [specs/product.md](specs/product.md) 与 [specs/benchmark.md](specs/benchmark.md) — 目标与最终硬门槛。

## 切片规则

- 任何产品行为变更先在 `specs/tasks/` 建任务规格（`.md` + `.json`），列出关联需求/案例 ID 与准确文件范围；task/base 检查会拒绝越界改动。
- 先写会失败的正例/负例测试，再实现；不为让旧测试保持绿色而保留错误语义。
- 每次提交可独立验证：`make verify` 通过且任务范围内无未声明文件。
- 不修改 gold/分母/预算/指标来制造结果；未完成的案例如实登记（planned/implementing/blocked）。

## 环境与测试

```bash
python3 -B -m unittest discover -s tests   # 全部测试（自建临时输入/输出，不依赖顺序）
make verify                                # 结构检查 + 测试
python3 -B scripts/check_specs.py --task specs/tasks/<task>.json --base <ref>
```

核心零第三方依赖（Python ≥3.9 声明，目标矩阵见 roadmap）；可选增强依赖不得进入核心路径。

## 提交约定

- 提交信息用祈使句简述变更（如 `fix: 不再把图丢失误报为 no-op`），复杂变更附任务 ID。
- 不提交用户资料、真实仓库正文、凭证、生成图/缓存（.gitignore 已排除 `out/`、`dist/`）。
- 无 CLA；贡献遵循仓库 MIT 许可。
