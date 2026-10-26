# Production boundaries：证据不可变与有界协议

日期：2026-10-24。关联 R01/R02/R03/R08/R11/R13/F2；案例见同名 manifest。本切片不代表生产阶段整体完成。

## 问题与第一性原理

知识库的最小价值是“此 ID 可重新核对同一来源、同一版本的材料”。代码长度、接口数量、绿灯数量不能替代该不变量。当前 CLI/MCP/UI 先把 ev_id 转为 sid，再取该来源最新版；再次摄入后，旧引用会悄悄变成新内容。内容相同的不同来源共用 ev_id，后写入覆盖出处。现有 store 测试只修改源文件，没有重新摄入，未触发真正的版本迁移反例。

另一基础条件是一个坏客户端请求不能终止服务。MCP 顶层数组/null 调用 `.get` 会退出；超长行先完整读取才检查；工具入参错误却返回 isError=false。

## 边界与契约

- `EvidenceStore.read_evidence(ev_id)` 是所有入口按 ID 读取的唯一服务；始终读取该记录指向的 blob，禁止重新解析到最新 sid。不存在返回 None，丢失/坏哈希返回 available=false 和稳定 reason，不回退源文件。
- 新 ID：`ev:` + SHA-256(canonical JSON([sid, blob_sha, locator]))；locator 含相对路径及截断标记。blob 内容寻址允许共用字节，证据身份独立。新插入只增不覆盖；旧 20 位 ID 原样兼容。历史记录已被覆盖的来源信息无法凭空恢复，明确登记限制。
- 最新来源指针存于现有 meta 的 `source_evidence:<sid>`，与来源更新同事务；复用旧版本或相同字节但不同截断标记时也不依赖插入时间。无该键的旧库按当前来源摘要和记录顺序兼容读取。sha256 表示固化片段摘要；超过 1 MiB 的来源仍明确标 truncated，不宣称整文件哈希。
- 例：来源 `a|README.md` 捕获 `v1` 得到 E1，重摄入 `v2` 得到 E2；`read_evidence(E1).text == "v1"`，`evidence_for_source(sid).ev_id == E2`。来源 `b|README.md` 的 `v1` 得到 E3 != E1。
- 同 rel 多来源的旧图缺少来源身份，不猜测仓库：共享 `evidence_map()` 仅映射唯一 sid，歧义不发布链接。图身份的全面重构另立任务。
- blob 临时文件按写者唯一命名；同 store 连接上的多线程调用用互斥锁覆盖完整操作，跨连接仍由 SQLite 串行发布。active generation 校验记录的内容哈希，不能仅凭“可解析 JSON”接受损坏数据。无新依赖、无数据库 schema 迁移。
- MCP 保留六工具及 Server.handle 的文本接口。stdio 校验 JSON-RPC 对象、方法、ID、params、工具入参和整数范围；错误保持有界，stdout 仅协议，正确通知无响应。单行最多 1 Mi 字符，分块排空超长行，再继续下一条请求；查询/符号/遍历参数各自有上限。工具 schema 与运行时约束同步。
- 输入源仍只由现有扫描边界登记。本片不修改排序、gold、基准预算、客户端配置、模型调用或发布策略。

## 文件与顺序

1. 先添加跨版本重摄入/跨来源副本/损坏 blob/损坏 generation/坏协议后继续读取的回归并记录失败。
2. 重构 store 的身份、精确读取、共享映射和并发临时文件；三入口改用服务；UI 仅改 Python 接线，保留在途工作台。
3. 加固 MCP framing/对象校验/工具错误；运行针对性及全量回归。
4. 写当前架构审计、记录生产缺口。progress 对过期证据标 implementing，保留历史 evidence 路径，不将不可重放客户端记录只改指纹升格。只有本次直接覆盖的案例可生成新的哈希证据。

manifest 中 CHANGELOG、product-ui-workbench 任务和测试是开始时已存在的未提交改动，仅为全 diff 范围检查登记；不归本片成果，不回退、不改写。原始 diff/UI/progress 已保存在 `out/refactor-production/`。

执行中出现 `.playwright-mcp/` 浏览器快照产物，保留原文件并在 .gitignore 忽略该生成目录，避免混入未来公开源码；不把它加入产品源码 allowlist。release gate 测试的“指名未完成案例”改用内存中的隔离状态，保留真实命令拒绝断言，避免误依赖本机旧 verified 状态；没有放宽检查器。

## Given / When / Then

- 同来源 v1→v2→删源→重开库：旧新 ID 各自保留固定正文、locator、哈希；CLI/MCP/UI 读同 ID 一致。
- 两来源同字节/相同相对路径：共享 blob，不共享身份；歧义路径没有任意最后写入者链接。
- blob 被删除/替换/变成链接：显式不可用，不返回当前文件或其他字节。
- 合法 JSON 的 generation 内容被改：active 检查拒绝，现有恢复流程据此重建。
- 同实例并发捕获/发布、跨实例相同 blob 捕获：不交叉提交，不因共用 `.tmp` 失败；操作失败可重试。
- stdio 数组/null/错误版本/非法 ID/超大行/非法 params/超范围整数后发 ping、tools/list：进程继续，响应 ID 正确，工具错误 isError=true，无 Traceback/正文泄露；通知不产生响应。

## 验证、限制与回退

先记录失败测试，再运行同名 JSON 所列命令。PDF 回归在 out 下隔离环境安装 pypdf==6.1.1，核心无需此依赖。结果、日志、指纹与 handoff 在 out 下，不上传。

回退只撤销本片代码改动；数据库无破坏性迁移。旧版 reader 不能正确解释新 ID 的外部映射，应保留数据库和对应新版应用一起回退/备份；旧 ID 的固化字节保持兼容。不删除 blob 或历史证据。

## 第二个有界切片：知识事务与非破坏恢复（实施前补充）

关联 AC-R05-01/AC-R07-01。共享 SQLite 连接的事务属于连接，不属于线程；BEGIN 不能替代线程互斥。一个失败的并发 BEGIN 可触发 context manager 回滚另一个线程的未提交笔记。读接口亦不能看到同连接上尚未确认的修改。新增 `storage.py` 只共享连接操作锁和读快照装饰器，EvidenceStore/KnowledgeStore 使用同一策略；不新增运行时或后端。

知识备份目前由备份完成后的实时库计算 manifest，其他进程写入会导致计数与备份不一致。恢复还在验证前覆盖目标，仅 assert notes 数量；优化模式会去掉断言。本切片将 manifest 从备份目标读取，v2 增加数据库 SHA-256/全部已知表计数；先在临时新库验证 schema、完整性、摘要和计数，再用不覆盖已存在路径的原子链接发布。目标及其 WAL/SHM/journal 任一存在则拒绝。验证失败清理临时文件、不创建目标；发布后同步/打开失败可能保留完整的已验证目标，不回退覆盖或删除。v1 仍可恢复，但严格检查其全部三项声明计数；没有内容摘要的限制不能消失。

例：已有 `current.db` 的正文是 A，归档正文是 B；restore 必须抛 FileExistsError，A 保留。篡改归档 manifest 的 revisions 值，恢复必须 ValueError，目标不存在。备份只包含人工知识库，不宣称已携带全工作区/固化证据；完整 R07 验收仍待整库导出切片。

文件新增：domimap/knowledge.py、domimap/storage.py、tests/test_knowledge_safety.py。先红后绿：共享连接并发保存、事务内读取隔离、已有库/符号链接目标、损坏 hash/notes/revisions/claims、未知 schema、备份期间跨连接写入、完整历史恢复与旧 v1 兼容。新增 backup 拒绝已有目录；restore 只接受干净目标。无权威表 schema 变更；回退代码前备份新格式归档，旧 reader 不读取 v2；v1 原始归档保留。

遗留：全来源/图/证据同次捕获与原子发布、整库证据恢复、MCP 完整生命周期/客户端版本协商、平台实测、独立正式比较。这些不因本片通过而完成。
