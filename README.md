# Curator

**Web version:** the new Curator landing and multi-user workspace use Next.js + Python, PostgreSQL, Tortoise ORM, asyncpg and Aerich. See [web setup](web/README.md). The existing `krystal-curator` CLI remains compatible.

Screener for LP pools listed on [Krystal](https://defi.krystal.app). Pulls the public
LP-explorer feed, applies a selectable **risk profile**, scores pools on *real* fee
yield + turnover + consistency, and shows the result in a Bloomberg-style terminal UI.

Default universe: Robinhood chain (4663), pools quoted in **USDG**, all protocols
(Uniswap v2/v3/v4, Ramses CL).

![krystal-curator TUI: ranked pools, detail pane, profiles, sort, watchlist, find, links, position size](demo/krystal-curator.gif)

## Quick start

```sh
make setup            # uv sync, write config.toml + .env templates, open them
make run              # TUI
make web-api          # FastAPI/uvicorn for the web workspace (:8100)
make web-ui           # Next.js frontend (:3000), other terminal
make config           # show effective settings + where they came from
make help             # every shortcut
```

Without make: `uv sync && uv run krystal-curator init && uv run krystal-curator`.

Precedence: **CLI flag > env var (`KRYSTAL_*`) > `config.toml` > default**. Secrets
(`KRYSTAL_WALLET` optional here, `KRYSTAL_CLOUD_KEY`, `TELEGRAM_*`) live in `.env`;
`config.toml` holds everything else (see `config.example.toml`) and is looked up in
`--config`, `$KRYSTAL_CONFIG`, `./config.toml`, then the user config dir.
`KRYSTAL_DATA_DIR` moves the sqlite db / cache (used by the container).

Commands: `tui` (default) · `scan` · `watch` · `setup` · `backtest` · `vault-review` · `vault-leaderboard` · `ask` (local-LLM addon) · `init` · `config` · `status`.

```sh
uv run krystal-curator --profile aggressive
uv run krystal-curator scan --top 20 --profile conservative --csv out.csv
uv run krystal-curator watch --telegram --digest-hour 0
uv run krystal-curator status      # daemon heartbeat, last alerts, history size
```

TUI: a nav strip on every screen — `1` screen · `2` positions · `3` leaderboard · `4` track · `5` agent · `,` settings ·
`:` command palette (profile, sort by column, quote, protocol, auto-refresh, export …) · `?` the keys of the current screen.
Screener keys: `enter` links popup · `o` open on Krystal · `*` watch · `W` watched only · `/` find · `r` refresh · `q` quit;
still bound, hidden from the footer: `u` quote · `p` protocol · `s`/`S` sort · `a` auto · `e` CSV · `$` size. Click a header to sort.
Settings (`,`) is a form over every `config.toml` value; `ctrl+s` validates, writes the file and applies what can change live
(profile, quote, protocols, size, refresh timer, alert thresholds, agent); chain / feed / renderer say `[restart]`.

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
of *observed active liquidity*. The delta is a prompt to look, not a verdict. Against the public instance the tool is a polite guest:
it asks for 1h and 24h only (7d / 30d time out there), one page of 150 pools each, one
request at a time, and leaves a window that answered 5xx alone for an hour. Against a
local `rhpools` (loopback URL) it asks for all four windows in parallel and retries after
10 minutes; `rhpools_windows` / `KRYSTAL_RHPOOLS_WINDOWS` overrides either default.
Windows not served are marked unknown, not zero-filled: rows show `7D?`, yield takes a
0.75× haircut instead of the `min(24h, 7d)` rule, and SPIKE/FADING are not claimed.

## Reliability

Every outbound call goes through one helper (`net.py`): transport errors and 408/425/429/5xx
are retried with exponential backoff and jitter, honouring `Retry-After`; a POST is retried
only when it provably never reached the server, so an alert is never sent twice. When a call
still fails, the text that reaches the log, the TUI or a Telegram reply has the bot token and
Cloud key scrubbed — Telegram puts the token in the URL, and httpx puts the URL in its errors.

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

## Vault review (`vault-review`)

```sh
uv run krystal-curator vault-review https://defi.krystal.app/vaults/4663/0xd674…
```

Reads one public AutoFarm vault end to end — no wallet, no key, no LLM — and writes a
dated Markdown + JSON snapshot to `reports/`: summary and open/closed strategies (detail
endpoint), the agent's goal, instructions, permissions, restrictions and execution
settings (`ai-agent-api.krystal.app/public-api/vault-agent-settings`), the newest action
plans with their on-chain outcome and error counts, and the TVL / fee series per window
with a fee APR re-derived from the buckets next to the feed's own. Every source that
failed is listed as failed, everything the public data cannot state (NAV per share,
cost semantics, plans beyond the first page) is listed under "not verifiable", and the
owner's instructions are quoted verbatim as data. The observations at the end are facts
about the source — exit not in the permissions, range floor below ours, APR-ranked
selection, a quote token other than USDG, rebalance series counted as one bet, pending
fees already inside `feeGenerated` — not a verdict.

The report ends with an **Evaluation** against our own limits (`vault_eval.Limits`: chain
4663, Uniswap v3/v4, USDG quote, ≤ 2 positions, second position ≤ 300 $, range ≥ 20 %
total, pool TVL ≥ 250 k$ with 150 k$ as a documented exception, cooldown ≥ 1 h). Three
separate answers: observed performance (closed positions counted as pair series, fees vs
price pnl, transaction costs), risk fit (one check per rule, each pass / fail / unknown
with its basis — `platform` for a control Krystal enforces, `instructions` for the
owner's free text, `data` for what the positions show), and evidence (age, series, plan
coverage, failed sources). The verdict is a rule, not a score: a platform-level fail is
`avoid` whatever the APR, thin evidence is `insufficient_data`, and only a vault whose
fee record pays for its price moves is `worth_testing` (with the instruction-level
adaptations listed); the rest is `watch`.

## Vault leaderboard (`L` in the TUI, `vault-leaderboard` on the CLI)

In the TUI, `L` opens the same board as a screen: `tab` flips between the vault table and
the owner table, `s` cycles the sort, `c` shows copy candidates only, `Enter` runs the
full review on the highlighted vault (≈ 5 requests, kept for the session) and shows the
verdict, its reasons and the failed checks in the right pane, `w` writes that vault's
report to `reports/`, `o` opens it on Krystal. The board is fetched once per session
(`r` refreshes).

```sh
uv run krystal-curator vault-leaderboard                 # every public AutoFarm vault on the chain
uv run krystal-curator vault-leaderboard --sort pnl --top 30
uv run krystal-curator vault-leaderboard --review 5 --write   # evaluate the top 5 candidates, write reports
```

Two questions, two tables, from the public vault list (`/all/v1/vaults?chainIds=`, no
wallet, no key). **Owners**: who is making money on the capital they run — every vault
of an owner aggregated, losers included, `ROI% = Σpnl / Σlifetime deposits`; owners with
less than `--min-tvl` (500 $) deposited are not ranked, a test balance is not a track
record. **Vaults**: copy candidates first, then the rest with the first rule they fail
next to them. A candidate is ≥ 14 days old (the evaluation's evidence floor,
`--min-age`), holds ≥ 500 $ (`--min-tvl`), has a positive pnl, has generated fees with
transaction costs at most half of them, and has its agent on (so there are settings to
copy). `--sort` picks `roi` (annualised pnl / deposited, default), `pnl` ($), `apr`
(the feed's fee APR) or `30d` (earning30d / TVL). `COPIES` is Krystal's own
`copyCount`, how many vaults were created by copying that one.

`--review N` runs the full `vault-review` evaluation on the top N candidates (≈ 5
requests each) and prints the verdict with its first reasons; `--write` also writes
each report to `--out`. The leaderboard ranks, the review decides: a vault with the best
ROI on the chain still comes back `avoid` when its permissions cannot exit or its range
floor is a platform setting below ours.

Numbers here are comparisons, not P&L: the feed's `pnl` does not reconcile with
value + withdrawn − deposited, so what it nets (costs? pending fees?) is unknown;
`userPerformance` on the public list is the vault's aggregate, not one depositor's;
lifetime deposits include re-deposits, so ROI is a floor on churny vaults.

## Local-LLM agent addon (`--agent`, `ask`, TUI `5`)

Off by default; nothing changes without it. It runs a small local model through
llama.cpp over the same read-only tools the rest of the program already has, and its
output is an *opinion next to* the rule verdict, never instead of it.

```toml
[agent]
enabled = true
model = "~/.lmstudio/models/openbmb/MiniCPM5-2B-GGUF/MiniCPM5-2B-Q8_0.gguf"
# base_url = "http://127.0.0.1:8081"   # reuse a llama-server you started yourself
```

```sh
brew install llama.cpp                                        # llama-server binary
uv run krystal-curator vault-review <URL> --agent             # report gains an "Agent reading" section
uv run krystal-curator vault-leaderboard --review 5 --agent   # the agent reads each reviewed vault
uv run krystal-curator ask "which copy candidates were also copied by others, top 3 with numbers?"
```

How it works: on first use we spawn `llama-server -m <model> --jinja -c 16384` (or attach
to `base_url`) and stop it on exit. Each step the model returns one JSON object — a
thought plus either one tool call or the final answer — and llama.cpp's grammar
enforces that schema token by token, so a 2B model cannot emit an unparsable step. The
tools: `limits`, `leaderboard`, `vault_review` (compact review + rule verdict + the
owner's instructions as quoted data), `pool`, `my_positions`. None writes, sends or
spends. The loop caps tool calls (`max_steps`, 8), executes an identical call only once,
and when the budget is gone or one tool is called three times it switches to a
final-only grammar and demands the answer — a small model otherwise loops forever.
Thinking is off by default (`reasoning_budget = 0`): with it unlimited MiniCPM5-2B
spends its whole token budget reasoning and returns nothing (verified); a positive
budget is passed as `--reasoning-budget` to the server we spawn.

In the TUI, `5` opens the AGENT screen (a question box over the same tools; `tab` leaves
the box so `1-5` navigate again) and on the leaderboard `a` runs the agent reading of the
highlighted vault — the rule review first if it has not run — into the detail pane, and
`w` writes both into the report.

What the report gets: a plain-words reading of the owner's instructions and positions,
`what_to_copy`, `what_to_change` (each with the limit it violates), a draft of the
instructions rewritten for our limits, verbatim evidence, whether the agent agrees with
the rule verdict, and a trace of every tool call. Any number in the answer that never
appeared in a tool result is listed as **unverified** — the model does invent figures.
Measured on an M-series Mac with the 2B Q8: one vault review ≈ 15–25 s, a leaderboard
question ≈ 20–40 s.

## Assumptions about the Krystal API

- `priceVolatility` is treated as a daily σ in percent — **unverified**, see `backtest --sigma`.
- `ageInSecond` on closed vault strategies is the hold time (open → close), not time since
  open — **verified** 2026-09-16 on a public vault with 201 closed strategies: ages are
  uncorrelated with strategy id (Spearman 0.10), the oldest ids have ages of minutes, and
  the one open strategy reports 216 days.
- `feeTier` is already a percent; vault `feeGenerated` includes pending fees; token
  `usdPrice` is empty on Robinhood, so prices come from `tvlTokenN / balanceN`.
- Vault `apr`, strategy `apr` and performance-bucket `apr` are fractions (5.13 = 513 %; `vaults.py` converts to percent on parse); vault/strategy `maxTotalCost` = transaction costs spent; the agent
  settings' `maxValuePerStrategy` 0.15 with unit `%` is 15 % of TVL (verified: a 302 $ cap
  on a ~2,015 $ vault); `sharePriceUsd` is 0 on public vaults, so no drawdown from NAV.

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

## License

Copyright (c) 2026 Dimas Victor. Released under the
[GNU Affero General Public License v3.0 only](LICENSE) (`AGPL-3.0-only`): use, study and
modify it freely, but any modified version you distribute or run as a network service must
be published under the same license. Data feeds keep their own terms; this tool consumes
Krystal, DexScreener and robinhoodpools over public HTTP and redistributes none of them.
