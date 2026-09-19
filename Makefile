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
WEB_HOST ?= 127.0.0.1
WEB_PORT ?= 8100

.PHONY: help install setup run scan watch status config backtest test lint fmt check \
        web web-api web-migrate web-ui \
        docker-build docker-up docker-down docker-logs docker-status docker-shell \
        install-mac uninstall-mac logs-mac install-linux uninstall-linux logs-linux clean demo

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

# ---- web -------------------------------------------------------------------
# Landing + /demo work without this. Login and /app need .env.web and Postgres.
web-api: ## FastAPI/uvicorn for the web workspace (:8100)
	@test -f .env.web || { \
	  echo "missing .env.web (CURATOR_DATABASE_URL and CURATOR_API_SECRET)."; \
	  echo "copy .env.web.example to .env.web, then: make web-api"; \
	  exit 1; \
	}
	$(UV) run --env-file .env.web --extra web uvicorn krystal_curator.web_api:app \
	  --host $(WEB_HOST) --port $(WEB_PORT) --reload --reload-dir src

web: web-api ## alias for web-api

web-migrate: ## apply Aerich migrations (Postgres from .env.web)
	@test -f .env.web || { \
	  echo "missing .env.web (CURATOR_DATABASE_URL)."; \
	  echo "copy .env.web.example to .env.web, then: make web-migrate"; \
	  exit 1; \
	}
	$(UV) run --env-file .env.web --extra web aerich upgrade

web-ui: ## Next.js frontend (:3000); run make web-api in another terminal
	npm run dev --prefix web

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
# ---- demo ------------------------------------------------------------------
# vhs (brew install vhs) records the TUI to PNG frames; ffmpeg turns them into the README GIF.
# vhs's own GIF step fails silently with ffmpeg ≥ 8, so the tape outputs frames instead.
# The tape copies no wallet in and points KRYSTAL_DATA_DIR at a scratch copy of the history db.
DEMO_DATA := $(shell mktemp -d)
demo: ## re-record demo/krystal-curator.gif (needs vhs, ffmpeg, a Chromium-based browser, network)
	@cp "$$HOME/Library/Application Support/krystal-curator/curator.sqlite3" $(DEMO_DATA)/ 2>/dev/null || true
	rm -rf demo/frames
	KRYSTAL_DATA_DIR=$(DEMO_DATA) vhs demo/demo.tape
	ffmpeg -hide_banner -loglevel error -y -framerate 50 -i demo/frames/frame-text-%05d.png \
	  -vf "fps=12,mpdecimate=hi=256:lo=128:frac=0.1,scale=1400:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" \
	  -fps_mode passthrough demo/krystal-curator.gif
	rm -rf demo/frames $(DEMO_DATA)
	@ls -la demo/krystal-curator.gif

clean: ## remove caches, exports, reports
	rm -rf .pytest_cache .ruff_cache exports reports
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
