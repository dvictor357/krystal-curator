# krystal-curator — quick commands. `make help` lists them.
SHELL := /bin/bash
UV ?= $(shell command -v uv 2>/dev/null || echo /opt/homebrew/bin/uv)
IMAGE ?= krystal-curator:latest
PLIST := app.krystal-curator.watch.plist
LAUNCHD := $(HOME)/Library/LaunchAgents/$(PLIST)
UNIT := krystal-watch.service
SYSTEMD := /etc/systemd/system/$(UNIT)
PWD_ := $(shell pwd)

.DEFAULT_GOAL := help
.PHONY: help install setup run scan watch status config backtest test lint fmt check \
        docker-build docker-up docker-down docker-logs docker-status docker-shell \
        install-mac uninstall-mac logs-mac install-linux uninstall-linux logs-linux clean

help: ## show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[33m%-16s\033[0m %s\n",$$1,$$2}'

# ---- local -----------------------------------------------------------------
install: ## uv sync (all groups)
	$(UV) sync --all-groups

setup: install ## write config.toml + .env templates if missing, then open them
	@$(UV) run krystal-curator init || true
	@echo "edit config.toml (profile, size, wallet, telegram, digest_hour) and .env (secrets)"
	@$${EDITOR:-nano} config.toml .env

run: ## TUI
	$(UV) run krystal-curator

scan: ## ranked table (ARGS="--profile aggressive --top 20")
	$(UV) run krystal-curator scan $(ARGS)

watch: ## daemon in the foreground
	$(UV) run krystal-curator watch $(ARGS)

status: ## daemon heartbeat + history
	$(UV) run krystal-curator status

config: ## effective configuration
	$(UV) run krystal-curator config

backtest: ## score vs forward yield on local history
	$(UV) run krystal-curator backtest $(ARGS)

test: ## pytest
	$(UV) run pytest -q

lint: ## ruff check + format check
	$(UV) run ruff check src tests && $(UV) run ruff format --check src tests

fmt: ## ruff format + autofix
	$(UV) run ruff format src tests && $(UV) run ruff check --fix src tests

check: lint test ## lint + test

# ---- docker ----------------------------------------------------------------
docker-build: ## build the image
	docker build -t $(IMAGE) .

docker-up: ## start the watch daemon (compose, detached, rebuilds)
	@test -f config.toml -a -f .env || { echo "run: make setup"; exit 1; }
	docker compose up -d --build

docker-down: ## stop the daemon
	docker compose down

docker-logs: ## follow daemon logs
	docker compose logs -f watch

docker-status: ## status inside the container
	docker compose exec watch krystal-curator status

docker-shell: ## shell inside the container
	docker compose exec watch bash

# ---- macOS launchd ---------------------------------------------------------
install-mac: ## install + start the launchd agent (this checkout, this uv)
	@test -f config.toml -a -f .env || { echo "run: make setup"; exit 1; }
	@mkdir -p $(HOME)/Library/LaunchAgents
	@sed -e 's#/Users/you/Projects/web3/krystal-curator#$(PWD_)#' \
	     -e 's#/opt/homebrew/bin/uv#$(UV)#' deploy/$(PLIST) > $(LAUNCHD)
	-launchctl unload $(LAUNCHD) 2>/dev/null
	launchctl load $(LAUNCHD)
	@echo "installed $(LAUNCHD); logs: make logs-mac"

uninstall-mac: ## stop + remove the launchd agent
	-launchctl unload $(LAUNCHD) 2>/dev/null
	rm -f $(LAUNCHD)

logs-mac: ## follow launchd logs
	tail -f /tmp/krystal-watch.log

# ---- linux systemd ---------------------------------------------------------
install-linux: ## install + start the systemd unit (needs sudo; this checkout, this user)
	@test -f config.toml -a -f .env || { echo "run: make setup"; exit 1; }
	@sed -e 's#/opt/krystal-curator#$(PWD_)#' -e 's#User=curator#User=$(USER)#' \
	     -e 's#/usr/local/bin/uv#$(UV)#' deploy/$(UNIT) | sudo tee $(SYSTEMD) >/dev/null
	sudo systemctl daemon-reload
	sudo systemctl enable --now $(UNIT)
	@echo "installed $(SYSTEMD); logs: make logs-linux"

uninstall-linux: ## stop + remove the systemd unit
	-sudo systemctl disable --now $(UNIT)
	sudo rm -f $(SYSTEMD)
	sudo systemctl daemon-reload

logs-linux: ## follow systemd logs
	journalctl -u $(UNIT) -f

# ---- misc ------------------------------------------------------------------
clean: ## remove caches, exports, reports
	rm -rf .pytest_cache .ruff_cache exports reports
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
