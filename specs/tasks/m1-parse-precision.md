# m1-parse-precision：重载签名、字段别名、空方法与嵌套边界 + 有限解析试验

- 关联：R01（AC-R01-01 的 given 含"重载"，本切片补齐后刷新该案例证据）、R09（构造正确/未知可见，M4 矩阵的前置）。
- 问题：①重载方法共点（id 无签名维度）；②字段名≠类名小驼峰时调用解析不到（如 `private Overload overload;`）；③lambda/匿名类内调用被记到外层方法（假归属）。
- 预期结果：重载按参数个数独立（`mth:{svc}:{Cls}.{name}#{argc}`，跨行签名 argc=-1 显式未知）；字段声明类型参与接收者解析；lambda/匿名上下文调用保守跳过并记 coverage；调用目标存在重载时产 AMBIGUOUS 边（不默取第一个）。
- 边界：lite 正则不做参数类型级 dispatch（可见未知）；直接 Java AST 小试（javalang 固定版本）只记录成本与差异，不在本切片切换主路径。

## 正例/负例（tests/test_precision.py，先红后绿）

1. Overload.changePrice#2 与 #1 独立成节点；caller 的裸调用 changePrice 因同类重载歧义产 AMBIGUOUS 边（不默指 #2 或 #1）。
2. `overload.changePrice("alias")` 经字段声明（Overload overload）解析 → INFERRED CALLS 边到 Overload.changePrice#1（唯一字符串重载？不——changePrice#1 是 (String) ✓ 字面量无法判定但目标类方法名唯一匹配 #1？"changePrice" 在 Overload 有 #2/#1 两版本 → 字段类型已知 Overload，仍两候选 → AMBIGUOUS。修正期望：断言产 AMBIGUOUS 边且不产唯一 INFERRED 假边）。
3. 空方法 doNothing 产生节点且不崩溃。
4. lambda/匿名内 helperCall 调用不产生归属于 outer 的确定 CALLS 边（保守跳过 + coverage 记录）。

## 解析试验（scripts/ast_trial.py + docs/implementation/parse-trial.md）

- venv 固定版本安装 javalang==0.13.0（纯 Python Java AST），对同一 precision 夹具抽取类/方法签名/调用点，输出与 lite 的 owner/signature 差异对比与安装成本；结论与主路径选择记录在 parse-trial.md。安装失败如实记 blocked。

## 验证与回退

- `python3 -B -m unittest tests.test_precision tests.test_golden -v`；`make verify` 全绿；task diff `--base a87488f`；`refresh_evidence.py m1-parse-precision a87488f`；AC-R01-01 证据 command 增加 tests.test_precision。
- 回退：revert 任务文件；mth id 增加 #argc 后旧图产物由版本门控重建。
