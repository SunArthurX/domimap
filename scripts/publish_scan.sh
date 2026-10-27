#!/bin/zsh
# AC-R11-02（R11）：推送/发布前的净化扫描——待上传差异不含密钥/用户数据/生成物，且文件集在 allowlist 内。
# 用法：bash scripts/publish_scan.sh [BASE]   # BASE 缺省 origin/main（推送前）或上一 tag（发布时）
set -e
BASE="${1:-origin/main}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "== publish_scan: base=$BASE =="
echo "-- 待上传提交 --"
git log --oneline "$BASE"..HEAD | head -30
echo "-- 变更文件集 --"
git diff --name-only "$BASE"..HEAD > /tmp/dm-pubscan-files.txt
cat /tmp/dm-pubscan-files.txt

echo "-- allowlist 检查（只允许源码/测试/规范/文档/CI/打包元数据） --"
BAD=$(grep -v -E '^(domimap/|tests/|specs/|docs/|scripts/|benchmarks/(protocol|evaluate|runners|real_tasks/run\.py|adapters)[^/]*/|\.github/|README|CHANGELOG|Makefile|pyproject|LICENSE|SECURITY|CONTRIBUTING|THIRD_PARTY|\.gitignore|AGENTS|SOUL)' /tmp/dm-pubscan-files.txt || true)
if [ -n "$BAD" ]; then echo "✗ allowlist 外的文件："; echo "$BAD"; exit 1; fi
echo "✓ 全部在 allowlist 内"

echo "-- 生成物/数据文件检查（图/库/快照/日志不得上传） --"
if grep -E '\.(db|json\.gz|idx\.json|log)$|(^|/)out/|graph\.json$|blobs/|gens/|queries\.db|knowledge\.db|store\.db' /tmp/dm-pubscan-files.txt; then
  echo "✗ 发现生成物/数据文件"; exit 1
fi
echo "✓ 无生成物/数据文件"

echo "-- 密钥/令牌模式扫描（差异内容） --"
if git diff "$BASE"..HEAD | grep -n -i -E 'sk-[a-zA-Z0-9]{16,}|api[_-]?key["'"'"':= ]+[A-Za-z0-9_\-]{16,}|BEGIN (RSA|EC|OPENSSH) PRIVATE KEY|password["'"'"':= ]+["'"'"'][^"'"'"']{6,}|ghp_[A-Za-z0-9]{20,}|Bearer [A-Za-z0-9_\-\.]{20,}' ; then
  echo "✗ 差异中出现疑似密钥模式"; exit 1
fi
echo "✓ 无密钥模式"

echo "-- 私有语料路径/用户数据泄露检查 --"
# 通用规则：任何本机家目录下的绝对路径都不应出现在公开差异里（不嵌入具体用户名/语料名）
if git diff "$BASE"..HEAD | grep -n -E '/Users/[A-Za-z0-9_.-]+/(work|Downloads|Documents)/' ; then
  echo "⚠ 差异中出现本机家目录绝对路径（确认是否可公开引用）"
fi
echo "== publish_scan 通过 =="
