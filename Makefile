.PHONY: help install uninstall test lint format doctor clean status logs daemon-restart

REPO := $(shell pwd)
VENV := $(HOME)/.local/share/recordo/venv
PY   := $(VENV)/bin/python

help: ## Lista alvos disponíveis
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Instala Recordo (setup.sh)
	bash $(REPO)/setup.sh

install-full: ## Instala + faster-whisper já
	bash $(REPO)/setup.sh --with-transcribe

uninstall: ## Desinstala (preserva venv + config)
	bash $(REPO)/uninstall.sh

purge: ## Desinstala + remove venv + config
	bash $(REPO)/uninstall.sh --purge

doctor: ## Roda diagnóstico
	bash $(REPO)/doctor.sh

test: ## Roda pytest (precisa venv com [dev])
	$(PY) -m pytest tests/ -v

lint: ## Roda ruff
	$(PY) -m ruff check src/ tests/

format: ## Formata com ruff
	$(PY) -m ruff format src/ tests/

shellcheck: ## Lint bash scripts
	shellcheck setup.sh uninstall.sh doctor.sh bin/* vicinae/*.sh keybindings/*.sh

status: ## Status do daemon
	systemctl --user status recordo --no-pager || true
	@echo ""
	@$(HOME)/.local/bin/recordo --status 2>/dev/null || true

logs: ## Tail dos logs
	tail -f /tmp/recordo.log /tmp/recordo.daemon.log

daemon-restart: ## Restart do daemon
	systemctl --user restart recordo

clean: ## Limpa caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf dist/ build/ *.egg-info src/*.egg-info
