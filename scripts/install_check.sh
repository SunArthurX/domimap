#!/bin/bash
# 干净环境安装检查（CI 与本地同用）：build → 新 venv 安装 wheel → 异目录 domimap 冒烟。
set -e
cd "$(dirname "$0")/.."
echo "== [1/4] build sdist/wheel =="
python3 -B -m pip install --quiet build 2>/dev/null || true
rm -rf dist  # 版本变更后残留旧 wheel 会让 "pip install dist/*.whl" 多版本冲突
python3 -B -m build --outdir dist >/dev/null
ls dist/*.whl
echo "== [2/4] 全新 venv =="
VENV=$(mktemp -d)/venv
python3 -m venv "$VENV"
echo "== [3/4] 安装 wheel =="
"$VENV/bin/pip" install --quiet dist/*.whl
echo "== [4/4] 异目录冒烟（不依赖源码目录/PYTHONPATH） =="
SMOKE=$(mktemp -d)
cd "$SMOKE"
"$VENV/bin/domimap" doctor | head -2
"$VENV/bin/domimap" build "$OLDPWD/tests/fixtures/mini" -o out | tail -1
"$VENV/bin/domimap" query "price_version" -g out/mini/graph.json | head -2
echo "== install-check OK =="
