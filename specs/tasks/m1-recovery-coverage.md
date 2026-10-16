# m1-recovery-coverage：边集等价、故障注入与 coverage 枚举契约

- 关联：R03（AC-R03-02 的"规范化集合等价"从节点集升级为节点+边集；扫描中变更/双写者/磁盘满注入）；R02（coverage 未解析项枚举：解析失败/旧格式/超限/越界/lambda 未知各有 file+reason）。
- 问题：AC-R03-02 证据只比节点集；扫描中源变更、双写者竞争、磁盘满无故障注入契约；coverage 各跳过原因无夹具级契约。
- 实现：`batch.normalized(g)` 返回 (节点集, 规范化边集(src,dst,kind,conf,prov))；其余为测试侧注入（monkeypatch os.replace 模拟 ENOSPC、包裹 _walk 模拟扫描中变更、双线程 build_many）。
- 正例/负例（tests/test_recovery_coverage.py，先红后绿）：
  1. 单文件变更→增量 update 与全量 force 的节点集+边集完全等价；
  2. 扫描中源被写入：扫描完成、捕获 sha 等于旧或新版本之一（原子视图，不崩溃）；
  3. 双写者并发 build_many 同一工作区：均完成、active 完整、无混代；
  4. 磁盘满（os.replace→OSError ENOSPC）注入发布：active 保持上一完整代，恢复后可发布；
  5. coverage 夹具（坏 mapper XML/legacy.doc/超限大文件）：三类跳过各带 file+reason 枚举。
- 范围补充：domimap/lite_scan.py —— .doc 扩展名此前在分发守卫处被 continue（旧格式提示分支是死代码），本次修复使其进入显式登记路径。
- 验证：unittest tests.test_recovery_coverage -v；make verify；task diff --base 42fb48f；refresh_evidence（AC-R03-02 证据扩展至新契约）。
- 回退：revert 任务文件；fixtures 为合成夹具。
