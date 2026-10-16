PY ?= python3
export PYTHONDONTWRITEBYTECODE = 1

test:
	$(PY) -B -m unittest discover -s tests -v
spec-check:
	$(PY) -B scripts/check_specs.py
verify: spec-check test
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
.PHONY: test spec-check verify release-check clean mini real serve doctor
