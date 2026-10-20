PY ?= python3
export PYTHONDONTWRITEBYTECODE = 1

test:
	$(PY) -B -m unittest discover -s tests -v
spec-check:
	$(PY) -B scripts/check_specs.py
# 本地门禁：结构校验 + 证据指纹/工件哈希校验 + 全部测试（verified 状态只由此确认）
verify: spec-check test
# 无本地证据工件的环境（CI / 新克隆）：结构校验 + 全部测试；不确认 verified 状态
spec-check-structural:
	$(PY) -B scripts/check_specs.py --structural
ci: spec-check-structural test
release-check:
	$(PY) -B scripts/check_specs.py --release
clean:
	$(PY) -B scripts/clean.py
mini:
	$(PY) -m domimap build tests/fixtures/mini -o out
	$(PY) -m domimap query "订单改价 防并发" -g out/mini/graph.json
# 扫描真实仓库：make real REAL_REPO=/path/to/your/java/repo
REAL_REPO ?= tests/fixtures/repo-belt
real:
	$(PY) -m domimap build $(REAL_REPO) -o out
	$(PY) -m domimap domain -g out/$(notdir $(REAL_REPO))/graph.json
serve:
	$(PY) -m domimap serve -g out/mini/graph.json
doctor:
	$(PY) -m domimap doctor
.PHONY: test spec-check verify spec-check-structural ci release-check clean mini real serve doctor
