# git-signature — 未改动文件用 Git blob id

日期：2026-10-28。计划 T11 的剩余部分。

## 问题

`update` 判断仓有没有变时，把每个文件读一遍做 sha256。Git 仓里大多数文件没改过。

## 预期

- 有 `.git` 时，`git ls-files` 里且 `git status` 显示干净的文件，签名是 `git:` 加 index blob id，不读工作区。
- 已修改或未跟踪的文件仍读字节做 sha256。
- 没有 `.git` 的仓签名不变，仍是文件 sha256。
- Git 仓建图后立刻 `update` 是 no-op。改工作区内容后签名不再是原来的 blob id。

## 回滚

`repo_signature` 恢复为一律读文件做 sha256。已有 `git:` 前缀的 manifest 会在下一次 update 时整仓重建。
