# m1-rebind：知识库移动/来源根重绑（AC-R01-02）

- given：知识库移动或来源根重新绑定；when：以原登记身份重新打开；then：逻辑身份保持；无依据的移动只提示重绑。
- 实现：`SourceRegistry.rebind(rid, new_path)` 更新物理绑定；sid=repo|rel 与路径无关 → 重绑后同文件同 sid；移动未重绑时 register 越界报错（提示重绑，不猜）。
- 测试（tests/test_identity.py 新增 TestRebind）：登记→save→目录改名→load→未重绑 register 报 OutOfRootError（提示）→rebind→register 得同一 sid/sha。
