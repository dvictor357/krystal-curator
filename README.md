# krystal-curator

Screener for LP pools listed on [Krystal](https://defi.krystal.app). Pulls the public
LP-explorer feed, applies a selectable **risk profile**, scores pools on *real* fee
yield + turnover + consistency, and shows the result in a Bloomberg-style terminal UI.

Default universe: Robinhood chain (4663), pools quoted in **USDG**, all protocols
(Uniswap v2/v3/v4, Ramses CL).

## Quick start

```sh
make setup            # uv sync, write config.toml + .env templates, open them
make run              # TUI
make config           # show effective settings + where they came from
make help             # every shortcut
```

Without make: `uv sync && uv run krystal-curator init && uv run krystal-curator`.

Precedence: **CLI flag > env var (`KRYSTAL_*`) > `config.toml` > default**. Secrets
(`KRYSTAL_WALLET` optional here, `KRYSTAL_CLOUD_KEY`, `TELEGRAM_*`) live in `.env`;
`config.toml` holds everything else (see `config.example.toml`) and is looked up in
`--config`, `$KRYSTAL_CONFIG`, `./config.toml`, then the user config dir.
`KRYSTAL_DATA_DIR` moves the sqlite db / cache (used by the container).

Commands: `tui` (default) · `scan` · `watch` · `setup` · `backtest` · `init` · `config` · `status`.

```sh
uv run krystal-curator --profile aggressive
uv run krystal-curator scan --top 20 --profile conservative --csv out.csv
uv run krystal-curator watch --telegram --digest-hour 0
uv run krystal-curator status      # daemon heartbeat, last alerts, history size
```

TUI keys: `1-4` profile · `u` toggle USDG-only · `p` cycle protocol · `s` next sort column · `S` asc/desc · click a header to sort by it · `*` watch/unwatch · `W` watched only · `a` auto-refresh on/off · `$` position size ·
`r` refresh · `o` open pool on Krystal · `l` or `Enter` open the links popup (pool page + website / X / Telegram / Discord …, Enter opens) · `e` export CSV to `exports/` · `/` find · `q` quit.

The `LINKS` column shows which socials each pool's tokens have (sortable). `TX1H` / `TX24`
are swap counts from DexScreener (free, 90 s cache): green 1h = pace ≥1.5× the daily
average, red = <0.3×. The detail FLOW row adds 5m/6h counts, average trade size and the
1h buy share. `LIVE` is the same idea in dollars (last-hour volume vs daily pace).

The detail panel shows both token logos and clickable social links. Logo renderer: `--images auto|tgp|sixel|halfcell|unicode|off` or `KRYSTAL_IMAGE=…`. `auto` uses Kitty/Sixel graphics (Ghostty, Kitty, WezTerm, iTerm2); Warp is detected and gets coloured half-blocks since it does not render graphics escapes.

## Pool feeds

`pool_source = "krystal"` (default) reads Krystal's public LP-explorer feed on any chain.
`pool_source = "rhpools"` (or `--source rhpools`, `KRYSTAL_SOURCE=rhpools`) reads
[robinhoodpools](https://github.com/wock9000/robinhoodpools), an open-source indexer that
derives volume, fees, TVL and swap counts straight from Robinhood-chain events, USDG-quoted.
Public instance `https://rhpools.lol`; point `rhpools_url` at `http://127.0.0.1:8196` for a
local `rhpools` service. Robinhood (4663) only.

What changes with `rhpools`: swap counts (`TX24`) come free (no Cloud key); TVL for v4 pools is
the value of *observed active liquidity* (`tvl_basis`), not manager balance; volatility,
drawdown and LP-auto support are **unknown** — filters skip them, the risk grade assumes
mid-band, and rows carry `σ?`. Every refresh records the pool price, so once the TUI or
daemon has ≥12 h of history for a pool the blanks fill in from it: `σ` becomes realised
daily volatility over the last 7 days (same estimator as `backtest --sigma`), `dd24` the
worst peak-to-trough move in the last 24 h (needs ≥6 h), and the row shows `σ~` instead.
`scan` uses the same history if the daemon has been running.

**Reconcile.** `reconcile = true` (or `--reconcile`, `KRYSTAL_RECONCILE=1`) also fetches the
*other* feed on every refresh and adds an `SRCΔ` column: how far the other feed's TVL is
from the one you are looking at (`+50%` = other feed sees 50 % more; `v`/`f` suffix when
only volume or fees were comparable; `-` = not listed there). Green < 5 %, yellow < 15 %,
red beyond; sortable, and the detail panel shows all three deltas. Ramses CL pools have no
chain-side twin. Expect big TVL gaps on v4: Krystal reports pool value, rhpools the value
of *observed active liquidity*. The delta is a prompt to look, not a verdict. Windows the service cannot serve (the public instance answers
503 for 7d / 30d when aggregation times out) are dropped, not zero-filled: rows show `7D?`,
yield takes a 0.75× haircut instead of the `min(24h, 7d)` rule, and SPIKE/FADING are not
claimed. A failed window is retried after 10 minutes.

## Deployment

The daemon is the thing to deploy; the TUI is a client over the same sqlite db.

**Docker (any host):** `make setup && make docker-up` · `make docker-logs` · `make docker-status` · `make docker-down`.
`config.toml` is mounted read-only, secrets come from `.env`, history persists in the
`krystal-data` volume, digests land in `./reports`. The healthcheck fails when the last
tick is older than 3× the interval.

**macOS (launchd):** `make install-mac` · `make logs-mac` · `make uninstall-mac`.
**Linux (systemd, sudo):** `make install-linux` · `make logs-linux` · `make uninstall-linux`.

Both templates in `deploy/` get this checkout's path, user and `uv` substituted in, and
read `config.toml` + `.env` from it. Set `telegram = true` and `digest_hour` in
`config.toml` so the unit needs no flags.

## Profiles

| key | tvl ≥ | vol24 ≥ | σ ≤ | dd24 ≤ | tier ≤ | new pools | lp-auto |
|---|---|---|---|---|---|---|---|
| conservative | 1M | 1M | 15% | 15% | 1% | no | required |
| balanced | 250K | 250K | 40% | 35% | 3% | no | required |
| aggressive | 50K | 100K | 70% | 60% | 6% | yes | required |
| degen | 10K | 25K | – | – | – | yes | – |

## Score (0–100)

Weighted per profile:

- **yield** – `min(fee24/tvl, fee7d/7/tvl)`; the lower of today vs 7-day average, so one spike day can't carry it
- **turnover** – `vol24 / tvl`; how hard the capital is actually working
- **consistency** – `fee24 / (fee7d/7)`; 0.7–1.5 is steady, >1.5 spike, <0.7 fading
- **liveness** – `vol1h*24 / vol24`; is it trading *now*
- **depth** – log-scaled TVL above the profile floor
- **risk** – inverse of price volatility and 24h drawdown

Live incentive rewards (gauges / Merkl, not killed) are added to the yield axis as
`dailyRewardUsd / tvl`.

`RK` (A–E) is a profile-independent risk grade. `AGE` is days since this tool first saw the
pool (a lower bound on its real age; `<1d` from the API's own stats). Flags: `NEW` (<1d
history), `YOUNG` (first seen <3d ago), `SPIKE`, `FADING`, `QUIET-1H`, `DYN-FEE`,
`EFFx%` (realised fee rate more than 30 % off the tier), `INCENTIVE`, `NO-AUTO`, `BLUE-CHIP`.

## My positions (`P`)

Needs only your wallet — `KRYSTAL_WALLET=0x…` in `.env` (gitignored) or `--wallet`. Krystal
vaults (auto-farm and VaultX) are read from the public API: every vault you own or joined,
with its TVL, PnL, APR, 24h/30d earnings, risk score and a closed-position track record
(count, win rate, realised PnL), and every open position inside them: value, deposit, PnL,
ROI, fees, pending fees, APR, age, a range bar (● = current price between min and max) and,
joined from the screener, the pool's grade / fee yield / volatility so you see when a pool
you are in has decayed. `c` toggles closed positions, `Enter` jumps the screener to that
pool, `o` opens the vault.

The detail pane shows a log-scale price ladder, each range edge's distance in %, in daily-σ
units (pool volatility) and in expected days for a random walk to reach it, realised fee/day
vs the pool's fee yield (are you capturing more or less than an average LP), and the pool's
screener health with its radar.

KRYSTAL SETUP block (also `krystal-curator setup`): the values to enter in Krystal's
Automation form for that position, labelled like the form — rebalancing trigger, time buffer,
new range ±% (σ·√hold-days for the active profile), swap / pool slippage, gas fee ceiling,
recurring, compound / harvest minimums, emergency-exit price. The daemon sends the same
list to Telegram whenever a new position appears. Nothing is signed or written to Krystal.

ROTATE block: the same dollars simulated in the screener's top pools for the active profile
(`1`–`4` switch it inside the view): my$/d, IL/d, net/d, share, uplift vs the position's
realised net, and payback of a 0.3 % switch cost. Verdict line says ROTATE / CONSIDER / STAY.
`x` opens the full ranked list; Enter jumps the screener to that pool.

Vault summary lines add idle capital (TVL not deployed in open positions), net result since
inception (value + withdrawn − deposited) and a TVL sparkline once history exists (vault
equity is snapshotted every 5 min into the local db).

`t` opens TRACK RECORD per vault (`tab` cycles vaults): equity / PnL / 24h-earnings
sparklines, capital deployed vs idle, since-inception result, and closed-position analytics —
count, win rate, realised PnL split into fees vs price, avg/median, hold time, best and
worst, breakdowns by protocol, fee tier and pair.

`e` writes an investor-style markdown report to `reports/vaults_<chain>_<time>.md`:
per vault summary, open positions table, closed track record and per-pair table.

Vaults are refetched on every screener refresh (free API), so monitoring runs without
opening `P`: the main top bar shows `POS:n OOR:k EDGE:m 24h+$`, and toasts fire when a
position leaves / re-enters range, an edge comes within 0.5σ, the pool's grade worsens, or
PnL drops by 5 % of value between refreshes.

With a Cloud key (`KRYSTAL_CLOUD_KEY`, https://cloud.krystal.app) the view also lists LP
NFTs held directly by the wallet — 10 units per refresh, on demand only (free tier 50,000).
The top bar counts units spent. `scan --tx` uses the same key for 24h transaction counts.

## Headless monitor + Telegram (`watch`)

```sh
uv run krystal-curator watch                   # uses config.toml (interval, telegram, digest_hour)
uv run krystal-curator watch --once            # one tick, for cron
```

Same refresh, snapshots and alert rules as the TUI, without a terminal. Alerts go to stdout
and, with `telegram = true`, to a Telegram chat:

```
TELEGRAM_BOT_TOKEN=123456:ABC…     # from @BotFather
TELEGRAM_CHAT_ID=123456789         # your user id (message the bot, then GET /getUpdates) or a group id
```

`digest_hour` writes the vault report at that UTC hour and sends it as a file. Alert
thresholds are in the `[alerts]` table of `config.toml`. `status` shows the heartbeat.

With Telegram on, the daemon is also a **bot**: message it from the configured chat.
`/menu` puts a persistent button bar under the chat (Positions · Scan · Rotate · Setup ·
Watchlist · Report · Profile · Size · Status); replies carry inline buttons for the next
step (pool detail, watch/unwatch, profile and size pickers, rotate/setup/report).

| command | what you get |
|---|---|
| `/pos` | vaults (tvl, pnl, 24h, idle, since-start, track record) + every open position with its nearest range edge in σ / days |
| `/scan [profile] [n]` | top pools: grade, yield, MY$/D, NET/D, share, swaps/24h |
| `/pool PAIR` | one pool: stats, flow, sim at your size, range suggestion, links |
| `/rotate` | rotation verdict + top-3 candidates per position |
| `/setup` | Krystal Automation values per position |
| `/watch PAIR` · `/unwatch` · `/watchlist` | starred pools (shared with the TUI) |
| `/size 20k` · `/profile degen` | change the sim size / risk profile (persisted) |
| `/report` | vault report as a file |
| `/mute [h]` · `/unmute` · `/status` · `/help` | |

Messages from any other chat id are ignored.

## Backtest (`backtest`)

```sh
uv run krystal-curator backtest --horizon 24 --days 14
```

Uses only the local snapshot history. For every refresh time T with a snapshot ~horizon
later, scores each pool as it looked at T and compares with the fee yield it delivered at
T+horizon: Spearman rank correlation per profile, top vs bottom decile forward yield, mean
forward yield of STEADY / FADING / SPIKE pools, and per-component correlations (which axes
actually predict). With a wallet it also compares the σ²/8 IL model against the realised
price PnL of your closed vault trades. Needs a day or two of TUI / `watch` history first.

`backtest --sigma` checks the one assumption every money number rests on: that the feed's
`priceVolatility` is a **daily** σ. Each snapshot stores the pool price (token0 in token1,
derived from the pool's USD and token balances), so after ~a day of history it computes the
realised daily σ per pool and the ratio realised / reported. Median ≈ 1 confirms daily;
≈ 0.38 means the feed is a 7-day σ (ranges 2.6× too wide, IL/d 7× too high); ≈ 0.18 →
30-day; ≈ 0.05 → annualised. Until the ratio is checked, treat IL/d, NET$/D, the ±range
and the Automation range width as unverified.

## Assumptions about the Krystal API

- `priceVolatility` is treated as a daily σ in percent — **unverified**, see `backtest --sigma`.
- `ageInSecond` on closed vault strategies is the hold time (open → close), not time since
  open — **verified** 2026-09-16 on a public vault with 201 closed strategies: ages are
  uncorrelated with strategy id (Spearman 0.10), the oldest ids have ages of minutes, and
  the one open strategy reports 216 days.
- `feeTier` is already a percent; vault `feeGenerated` includes pending fees; token
  `usdPrice` is empty on Robinhood, so prices come from `tvlTokenN / balanceN`.

## Position simulator

`--size 50000` (or `$` in the TUI) sets your position size. Every row then shows what *you*
would earn, not the pool headline:

- `MY$/D` – pool fee24 × your share, where share = size / (tvl + size) (dilution-adjusted)
- `SHARE` – your fraction of the pool after entering; ≥25 % flagged (you become the pool)
- `NET$/D` – `MY$/D` minus an impermanent-loss estimate of σ²/8 per day (full-range
  lognormal approximation, σ = Krystal `priceVolatility` treated as daily)

The detail panel adds APR at your size, 7d-basis fee, fee/IL coverage ratio, a suggested
±range that holds 68 % / 95 % of 7-day price outcomes (σ√7, 2σ√7), and how many days of
fees cover a 2σ move. Concentrated ranges scale fees and IL by roughly the same factor, so
the fee/IL ratio is the pool-selection signal; the range is the position-sizing one.

## Profiles

| key | tvl ≥ | vol24 ≥ | σ ≤ | dd24 ≤ | tier ≤ | new pools | lp-auto |
|---|---|---|---|---|---|---|---|
| conservative | 1M | 1M | 15% | 15% | 1% | no | required |
| balanced | 250K | 250K | 40% | 35% | 3% | no | required |
| aggressive | 50K | 100K | 70% | 60% | 6% | yes | required |
| degen | 10K | 25K | – | – | – | yes | – |

## Score (0–100)

Weighted per profile:

- **yield** – `min(fee24/tvl, fee7d/7/tvl)`; the lower of today vs 7-day average, so one spike day can't carry it
- **turnover** – `vol24 / tvl`; how hard the capital is actually working
- **consistency** – `fee24 / (fee7d/7)`; 0.7–1.5 is steady, >1.5 spike, <0.7 fading
- **liveness** – `vol1h*24 / vol24`; is it trading *now*
- **depth** – log-scaled TVL above the profile floor
- **risk** – inverse of price volatility and 24h drawdown

Live incentive rewards (gauges / Merkl, not killed) are added to the yield axis as
`dailyRewardUsd / tvl`.

`RK` (A–E) is a profile-independent risk grade. `AGE` is days since this tool first saw the
pool (a lower bound on its real age; `<1d` from the API's own stats). Flags: `NEW` (<1d
history), `YOUNG` (first seen <3d ago), `SPIKE`, `FADING`, `QUIET-1H`, `DYN-FEE`,
`EFFx%` (realised fee rate more than 30 % off the tier), `INCENTIVE`, `NO-AUTO`, `BLUE-CHIP`.

## Cloud API: your positions (`P`)

Needs a key from https://cloud.krystal.app and your wallet. Put both in `.env` (gitignored)
or the environment:

```
KRYSTAL_CLOUD_KEY=kc_...
KRYSTAL_WALLET=0x...
```

`P` opens MY POSITIONS: value, deposit, PnL, ROI, IL, pending/claimed fees, fee APR, age,
range position (● on a bar between min and max price) and, joined from the screener, the
pool's current grade / fee yield / volatility so you can see when a pool you're in has
decayed. `r` refetches (10 units per call — free tier is 50,000; nothing runs on the
auto-refresh timer). `Enter` jumps the screener to that pool. Out-of-range positions raise
a toast. The top bar counts units spent this session.

`scan --tx` (same key) fetches 24h transaction counts for the top rows, 10 units per pool.

## Dev

```sh
uv run pytest
uv run ruff check src tests && uv run ruff format src tests
```
