# 测试与夹具

在项目根目录运行：

```bash
make test
# 或
python3 -B -m unittest discover -s tests -v
```

| 文件 | 覆盖 |
|---|---|
| test_golden.py | 单仓框架规则、检索、领域与影响面 smoke |
| test_p1.py | 多仓、MQ/JPA、更新 no-op、场景卡与索引缓存 |
| test_replay.py | 历史查询/场景混合回放；不代表严格 Top-5 质量验收 |
| test_project_hygiene.py | 清理工具的预览、删除范围与符号链接边界 |
| test_spec_contracts.py | 需求/案例映射、任务 diff、假完成/过期证据与协议降级拒绝 |
| test_benchmark_metrics.py | 指标定义、伪命中/漏基线/打平/坏工件拒绝，合成不正式通过 |
| fixtures/ | 合成 Java 多仓与项目资料，作为只读测试输入 |

每个模块使用系统临时目录保存图、manifest 和缓存，结束后自动清理。缓存测试可单独运行，不依赖其他测试生成文件；使用 `-B` 或 Makefile 入口避免 Python 字节码缓存。

夹具回归不证明真实任务、生产可靠性或跨平台兼容已通过，正式验收要求见[生产主计划](../docs/roadmap.md)。
