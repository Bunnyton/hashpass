# hashpass — dev tasks. Run `make` (or `make help`) to list targets.
PY := python3
PYTEST := $(PY) -m pytest
TIER3_TMPDIR := /var/tmp/hp-pytest

.DEFAULT_GOAL := help
.PHONY: help install install-student update uninstall test test-tier3 lint clean

# --user -> ~/.local (not system); --break-system-packages for Debian PEP 668;
# --root-user-action=ignore silences pip's root warning (the pool is often run as root).
PIP_INSTALL := $(PY) -m pip install --user -e . --break-system-packages --root-user-action=ignore
ACTIVATE_ENGINE := mkdir -p "$(HOME)/.hashengine" && touch "$(HOME)/.hashengine/engine.enabled"

help:
	@echo "make install         — установить обе команды (hashpass + hashengine), editable"
	@echo "make update          — обновиться из git (безопасно, с autostash) и переустановить"
	@echo "make install-student — установить (сейчас ставит обе; отдельная студ.-дистрибуция — фаза 8)"
	@echo "make uninstall       — удалить"
	@echo "make test        — тесты tier1/tier2 (без контейнеров)"
	@echo "make test-tier3  — тесты tier3 (реальный systemd-nspawn + scoped sudo)"
	@echo "make lint        — ruff"
	@echo "make clean       — убрать __pycache__ / *.pyc"

install:
	$(PIP_INSTALL)
	$(ACTIVATE_ENGINE)

# One command to update: autostash puts any local changes aside and restores them, so a
# fast-forward is never blocked and you never have to clean the tree by hand.
update:
	git pull --ff-only --autostash
	$(PIP_INSTALL)
	$(ACTIVATE_ENGINE)

# Placeholder: one distribution still ships both scripts; the real student-only pip
# distribution (only the `hashpass` command, no engine code) lands with Phase 8.
install-student: install

uninstall:
	-$(PY) -m pip uninstall -y hashpass --break-system-packages --root-user-action=ignore

test:
	$(PYTEST) -m "not tier3"

test-tier3:
	TMPDIR=$(TIER3_TMPDIR) $(PYTEST) -m tier3

lint:
	ruff check --config ruff.toml src tests

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -name '*.pyc' -delete
