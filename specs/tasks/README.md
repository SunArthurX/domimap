# Task specs

每次产品切片新建 `<task>.md` 与 `<task>.json`，JSON 从 [task-template.json](../task-template.json)复制；填写真实需求、验收案例、准确文件和验证方式。不要把空模板当任务。

任务 Markdown 的六项内容见[开发工作流](../workflow.md)。运行：

```bash
python3 -B scripts/check_specs.py --task specs/tasks/<task>.json --base <local-git-ref>
```

`files` 是允许修改的准确项目相对路径，不能使用通配符；`test_files` 必须为其中的测试文件。任务自身、对应 Markdown 和 progress 可作为受管元数据更新。需要扩大文件范围时先记录原因并修改任务，不能直接绕过 diff 检查。

当前目录没有产品任务实例，意味着尚未开始 M1 功能实施；已增加的规格/评分工具属于 M0 开发基础设施。
