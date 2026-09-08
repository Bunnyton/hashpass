# hashpass — dev tasks. Run `make` (or `make help`) to list targets.
PY := python3
PYTEST := $(PY) -m pytest
TIER3_TMPDIR := /var/tmp/hp-pytest

.DEFAULT_GOAL := help
.PHONY: help install install-student uninstall test test-tier3 lint clean

help:
	@echo "make install         — установить обе команды (hashpass + hashengine), editable"
	@echo "make install-student — установить (сейчас ставит обе; отдельная студ.-дистрибуция — фаза 8)"
	@echo "make uninstall       — удалить"
	@echo "make test        — тесты tier1/tier2 (без контейнеров)"
	@echo "make test-tier3  — тесты tier3 (реальный systemd-nspawn + scoped sudo)"
	@echo "make lint        — ruff"
	@echo "make clean       — убрать __pycache__ / *.pyc"

# --user ставит в ~/.local (не в системный /usr); --break-system-packages нужен из-за PEP 668
# (Debian externally-managed). Внутри venv оба флага можно убрать.
install:
	$(PY) -m pip install --user -e . --break-system-packages
	mkdir -p "$(HOME)/.hashengine" && touch "$(HOME)/.hashengine/engine.enabled"  # activate hashengine here

# Placeholder: one distribution still ships both scripts; the real student-only pip
# distribution (only the `hashpass` command, no engine code) lands with Phase 8.
install-student: install

uninstall:
	-$(PY) -m pip uninstall -y hashpass --break-system-packages

test:
	$(PYTEST) -m "not tier3"

test-tier3:
	TMPDIR=$(TIER3_TMPDIR) $(PYTEST) -m tier3

lint:
	ruff check --config ruff.toml src tests

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -name '*.pyc' -delete
