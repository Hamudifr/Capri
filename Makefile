# Capri developer entry points. Run from the repository root.
# Toolchain: .toolchain/py315 (CPython 3.15 + bundled SQLite); C targets use cc.

PY := .toolchain/py315/bin/python3
export CPATH := .toolchain/sqlite2/include
export LIBRARY_PATH := .toolchain/sqlite2/lib
export LD_LIBRARY_PATH := .toolchain/sqlite2/lib:.toolchain/prefix/lib

.PHONY: help compile lint test doctor parity profile check

help: ## Show this help
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

compile: ## Byte-compile source, tests, benchmarks, scripts
	$(PY) -m compileall -q capri_core capri_runtime tests benchmarks scripts

lint: ## Static analysis: pyflakes over production code (tests intentionally hold references)
	$(PY) -m pyflakes capri_core capri_runtime scripts benchmarks || python3 -m pyflakes capri_core capri_runtime scripts benchmarks

test: ## Full unit suite (~1000 tests, ~15-20s)
	$(PY) -m unittest discover -s tests

doctor: ## Read-only repository health checks (7/7) + operational health (8/8)
	$(PY) -m capri_core doctor

parity: ## C session-store parity contract (exactly-4-lines stdout)
	$(PY) -m unittest tests.test_sqlite_session_parity

profile: ## cProfile the suite; print top cumulative frames
	$(PY) -m cProfile -s cumtime -o /tmp/capri-suite.prof -m unittest discover -s tests
	$(PY) -c "import pstats; pstats.Stats('/tmp/capri-suite.prof').sort_stats('cumulative').print_stats(25)"

check: compile lint test doctor ## Compile + lint + tests + doctor (pre-push gate)
	@echo "check: OK"
