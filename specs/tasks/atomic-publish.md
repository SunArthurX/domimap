# atomic-publish — D12：派生产物原子发布 + 内容哈希增量 + 兼容副本健康校验

日期：2026-10-26。依据 docs/superpowers/plans/2026-10-26-drift-analysis-and-priorities.md Task 6；关闭 docs/known-defects.md D12 与 D1 残留。

## 关联需求与案例

- R03：构建发布与更新恢复；任意发布中断不暴露混代/截断产物。
- AC-R03-01（每个发布阶段中断：读者只见上一完整代或新完整代）；AC-R03-02（图丢失/坏缓存/删改/规则变化：不误报 no-op）。

## 问题

`batch.publish_generation` 用 `shutil.copyfile` 原地截断写 graph.json（`-g graph.json` 是所有入口实际读取的文件），崩溃窗口内读者得到截断文件；coverage.json/manifest.json 直写；`_store_healthy` 只查 store 内 active 代与 seeds，不查兼容副本，graph.json 单独丢失/篡改误报 no-op（D1 残留）；manifest 文件签名 `[mtime_ns,size]`——`cp -p`/`touch -r` 后的同尺寸改写永久 no-op，合并图与源静默分叉（roadmap M1："不将路径/mtime 当内容版本"）。

## 预期用户结果

- `_atomic_write(path, bytes)`：tmp → fsync → `os.replace` → 目录 fsync；graph.json/coverage.json/manifest.json 全部经它落盘；崩溃中断时目标文件保持上一完整内容，残留 .tmp 在下次构建被覆盖重命名。
- `publish_generation`：active 代切换成功后，把该代文件字节原子写入 graph.json（字节相等，sha 相等）。
- `_store_healthy`：active 代存在且 seeds 一致 **且** graph.json sha256 == active.sha256；否则不健康 → update 重发布。
- manifest `files`：rel → 内容 sha256（扫描期 `_capture_into(store, label, signature)` 用同一份 raw 计算，不多读）；`repo_signature(root)` 读文件哈希用于 update 的 no-op 判定；旧 manifest（list 值）比对不等 → 首次 update 自愈重建。

## Given/When/Then

- 正例：manifest 签名全为 64 位 hex 且等于磁盘文件 sha；同尺寸改写 + 恢复 mtime → update rebuild，再次 update no-op；删 graph.json → update 重发布且节点集合等价；篡改 graph.json 为另一合法 JSON → update 重发布且 sha 回到 active；干净构建后无 .tmp 残留。
- 负例：注入兼容副本写入中途崩溃（tmp 写半截后抛 OSError）→ graph.json 仍为上一完整代、可加载、节点集合不变；恢复后 update 完成发布且无 .tmp。

## 设计选择

- 兼容副本按 active 代 sha 校验而非 mtime：mtime 不是内容版本。
- 增量判定接受"无变更也需重读全部文件"的 I/O 成本（≤2MiB/文件，秒级）换取正确性；文件级增量留给 AST 引擎阶段。
- active 切换与兼容副本落盘仍两步：中断窗口内两者都是完整快照，且 `_store_healthy` 在下次 update 自愈；不引入跨文件事务。

## 验证 / 回滚

见 manifest。628 tests OK（含 6 项新测试）。

## 遗留

- 整库导出恢复（T7）。
