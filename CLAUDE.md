# krystal-curator

Terminal screener + position monitor for Krystal LP pools (Robinhood chain first, USDG quote).
Python 3.13, `uv`, Textual TUI. Owner is an LP / vault manager; numbers drive real capital.

## Commands
- `uv sync --all-groups` · `uv run pytest -q` · `uv run ruff check src tests && uv run ruff format src tests`
- `uv run krystal-curator` (TUI) · `scan` · `watch` (daemon) · `backtest`
- Secrets in `.env` (gitignored): `KRYSTAL_WALLET`, optional `KRYSTAL_CLOUD_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
  Never commit `.env`, `exports/`, `reports/`.

## Layout (`src/krystal_curator/`)
- `api.py` public LP-explorer feed (free) + Cloud API helpers (paid units) · `enrich.py` DexScreener logos/socials · `vaults.py` vault + strategy positions (free public API) · `positions.py` Position model + Cloud `/v1/positions`
- `models.py` Pool + derived metrics · `profiles.py` risk profiles · `scoring.py` filters/score/grade/flags · `position.py` size simulator (dilution, σ²/8 IL) · `advisor.py` range-edge math · `rotation.py` opportunity cost · `analytics.py` track record / report
- `store.py` sqlite (pool + vault snapshots, watchlist) · `monitor.py` alert rules shared by TUI and daemon · `daemon.py` `watch` loop · `notify.py` Telegram · `backtest.py`
- `tui.py` + `tui.tcss` all screens (CuratorApp, PositionsScreen, TrackScreen, modals) · `cli.py` argparse entry

## Conventions
- Pure logic lives outside `tui.py` with unit tests; TUI tests run on `tests/fixtures/top_pools_robinhood.json` with network patched out (`tests/test_tui.py`).
- Cloud API calls only on explicit user action (never on timers); count units in `units_used`.
- Widgets are looked up on the base screen (`self.main`) because modals sit on top; never name a method `_render`, `_closed`, `_open`, `size` on Textual subclasses (clashes with internals).
- API facts learned by probing (not in docs): `feeTier` is already a percent; v4 pools are keyed by 32-byte pool id in the LP explorer but `poolAddress` in vault strategies; vault `feeGenerated` includes pending fees; Krystal token `links` are empty for Robinhood tokens (use DexScreener); vault positions are not returned by Cloud `/v1/positions`.
- Unverified assumptions, flagged in README: `priceVolatility` treated as daily σ; `ageInSecond` on closed strategies treated as hold time.
