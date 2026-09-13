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

TUI keys: `1-4` profile · `u` toggle USDG-only · `p` cycle protocol · `s` cycle sort ·
`r` refresh · `o` open pool on Krystal · `e` export CSV to `exports/` · `/` find · `q` quit.

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
