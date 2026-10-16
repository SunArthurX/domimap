#!/bin/bash
# domimap 环境检查（macOS/Linux；Windows 直接 py -3 -m domimap）
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
PY="${PY:-python3}"
echo "== domimap: $(uname -s) $(uname -m) =="
"$PY" --version || { echo "需要 Python 3.9+"; exit 1; }
echo "-- 核心（零依赖）自检"
"$PY" -B -m domimap doctor
echo "-- golden 测试"
"$PY" -B -m unittest discover -s tests
echo "可选依赖按需安装，见 README。"
echo "== 完成。试跑: python3 -m domimap build tests/fixtures/mini -o out =="
