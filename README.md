# krystal-curator

Screener for LP pools listed on [Krystal](https://defi.krystal.app). Pulls the public
LP-explorer feed, applies a selectable **risk profile**, scores pools on *real* fee
yield + turnover + consistency, and shows the result in a Bloomberg-style terminal UI.

Default universe: Robinhood chain (4663), pools quoted in **USDG**, all protocols
(Uniswap v2/v3/v4, Ramses CL).

## Install / run

```sh
uv sync
uv run krystal-curator                 # TUI, balanced profile, USDG pairs
uv run krystal-curator --profile aggressive
uv run krystal-curator scan --top 20 --profile conservative --csv out.csv
uv run krystal-curator scan --quote any --protocol ramsescl
```

TUI keys: `1-4` profile · `u` toggle USDG-only · `p` cycle protocol · `s` next sort column · `S` asc/desc · click a header to sort by it · `*` watch/unwatch · `W` watched only · `a` auto-refresh on/off · `$` position size ·
`r` refresh · `o` open pool on Krystal · `l` or `Enter` open the links popup (pool page + website / X / Telegram / Discord …, Enter opens) · `e` export CSV to `exports/` · `/` find · `q` quit.

The `LINKS` column shows which socials each pool's tokens have (sortable).

The detail panel shows both token logos and clickable social links. Logo renderer: `--images auto|tgp|sixel|halfcell|unicode|off` or `KRYSTAL_IMAGE=…`. `auto` uses Kitty/Sixel graphics (Ghostty, Kitty, WezTerm, iTerm2); Warp is detected and gets coloured half-blocks since it does not render graphics escapes. Logos and links come from DexScreener (no key), cached under the user cache dir for 6h.

## Watchlist, history, alerts

Every refresh is snapshotted to a local sqlite db (`~/Library/Application Support/krystal-curator`
on macOS): watched pools on every refresh, the wider universe every 15 min, kept 14 days.
That powers the `ΔFEE` column (fee24 vs ~24h ago), the `TREND` sparkline, the HISTORY line
in the detail panel (fee + TVL sparklines, Δ tvl/fee/vol), and watch alerts: a toast when a
starred pool's TVL moves ≥30 % in an hour, fee24 halves, or drawdown passes −30 %.
`--refresh 300` sets the auto-refresh period (0 = off). Cursor stays on the same pool across
refreshes and re-sorts.

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

`RK` (A–E) is a profile-independent risk grade. Flags: `NEW` (<1d history), `SPIKE`,
`FADING`, `QUIET-1H`, `DYN-FEE`, `INCENTIVE`, `NO-AUTO`, `BLUE-CHIP`.

## Optional: Cloud API

`export KRYSTAL_CLOUD_KEY=...` (from https://cloud.krystal.app) and `scan --tx` fetches
24h transaction counts for the top rows. Costs credits per pool; response parsing is
best-effort as the schema is undocumented.

## Dev

```sh
uv run pytest
uv run ruff check src tests && uv run ruff format src tests
```
