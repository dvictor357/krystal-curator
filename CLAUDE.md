# krystal-curator

Terminal screener + position monitor for Krystal LP pools (Robinhood chain first, USDG quote).
Python 3.13, `uv`, Textual TUI. Owner is an LP / vault manager; numbers drive real capital.

## Commands
- `uv sync --all-groups` · `uv run pytest -q` · `uv run ruff check src tests && uv run ruff format src tests`
- `uv run krystal-curator` (TUI) · `scan` · `watch` (daemon) · `backtest`
- Secrets in `.env` (gitignored): `KRYSTAL_WALLET`, optional `KRYSTAL_CLOUD_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
  Never commit `.env`, `exports/`, `reports/`.

## Layout (`src/krystal_curator/`)
- `api.py` `fetch_pools(source=…)` dispatch + Krystal LP-explorer feed (free) + Cloud API helpers (paid units) · `rhpools.py` robinhoodpools chain-indexed feed (`/api/lp/pools`, one request per window; public host = 1h+24h only, one page, sequential, 1-h cooldown after 5xx; loopback = all windows, parallel, 10-min cooldown; unserved windows → `Pool.unknown`) · `enrich.py` DexScreener logos/socials · `vaults.py` vault + strategy positions (free public API) · `positions.py` Position model + Cloud `/v1/positions`
- `net.py` the only HTTP door: `net.get/post/request` retry transport failures and 408/425/429/5xx with backoff + Retry-After (POST only when the request provably never arrived), raise `net.HttpError` with redacted text; `register_secret()` + `redact()` scrub the Telegram token and Cloud key from every error, toast and log (httpx/httpcore loggers filtered). Never call `httpx.get/post` directly outside net.py / rhpools.py's client.
- `models.py` Pool + derived metrics · `profiles.py` risk profiles · `scoring.py` filters/score/grade/flags · `position.py` size simulator (dilution, σ²/8 IL) · `advisor.py` range-edge math · `rotation.py` opportunity cost · `analytics.py` track record / report
- `reconcile.py` deltas of the other feed vs the primary per pool id (`Reconciliation`, `Recon`); `api.fetch_reference_pools` picks the other feed; `Scored.recon` feeds the `SRCΔ` column / detail row · `risk.py` fills unknown σ / drawdown from snapshot price history (realised, 7d / 24h; sets `volatility_basis`) — runs in `Monitor.tick` after the snapshot and in `scan` · `store.py` sqlite (pool + vault snapshots, watchlist) · `monitor.py` alert rules shared by TUI and daemon · `daemon.py` `watch` loop · `notify.py` Telegram · `bot.py` Telegram commands · `autoconfig.py` Krystal Automation form values · `backtest.py`
- `tui.py` + `tui.tcss` all screens (CuratorApp, PositionsScreen, TrackScreen, modals) · `cli.py` argparse entry

## Conventions
- `Pool.unknown` names metrics a feed did not provide (`volatility`, `drawdown`, `lp_auto`, `tvl`, `stat1h/7d/30d`); 0.0 there means unknown, never zero. Filters skip unknown metrics, scores treat them as neutral (0.5), flags that need them are not emitted. Any new rule reading those fields must check `unknown` first. Snapshots keep the feed's own values (unknown → 0.0), never the realised fill, so `backtest --sigma` compares feed vs realised, not realised vs itself.
- Pure logic lives outside `tui.py` with unit tests; TUI tests run on `tests/fixtures/top_pools_robinhood.json` with network patched out (`tests/test_tui.py`).
- Cloud API calls only on explicit user action (never on timers); count units in `units_used`.
- Widgets are looked up on the base screen (`self.main`) because modals sit on top; never name a method `_render`, `_closed`, `_open`, `size` on Textual subclasses (clashes with internals).
- API facts learned by probing (not in docs): `feeTier` is already a percent; v4 pools are keyed by 32-byte pool id in the LP explorer but `poolAddress` in vault strategies; vault `feeGenerated` includes pending fees; Krystal token `links` are empty for Robinhood tokens (use DexScreener); vault positions are not returned by Cloud `/v1/positions`.
- API facts verified by probing: `ageInSecond` on closed strategies is hold time (README "Assumptions"). Still unverified: `priceVolatility` treated as daily σ — `backtest --sigma` measures it from snapshot price history; token `usdPrice` is empty on Robinhood so `Pool.price0_usd/price1_usd` derive from `tvlTokenN / balanceN`.
