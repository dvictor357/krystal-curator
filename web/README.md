# Curator web

Next.js + a private FastAPI backend. Accounts, preferences and watchlists live in **PostgreSQL**, through **Tortoise ORM + asyncpg**, with **Aerich** migrations. The original Python CLI/TUI and collector history remain compatible. No managed account service is required.

## Run locally

From the repository root:

```sh
uv sync --extra web
npm ci --prefix web
```

Create a PostgreSQL database and a dedicated database user. Configure the Python process using `.env.web.example` as your template, stored locally as `.env.web` (ignored by git):

- `CURATOR_DATABASE_URL`: PostgreSQL connection URL (`postgres://...`).
- `CURATOR_API_SECRET`: at least 32 random characters; use the same value in both processes.
- `CURATOR_COOKIE_SECURE=false`: local HTTP only. Omit it or use `true` behind HTTPS.
- `TELEGRAM_BOT_TOKEN` (optional): enables per-user position alerts. Users paste their chat ID in Settings and press "Send test"; the API process runs one alert tick every `CURATOR_ALERT_INTERVAL` seconds (default 300), leased through `curator_jobs` so several workers do not double-send. Rules: out of range, range edge within 0.5σ, pool grade decay, PnL drop ≥ 5 %, rotation verdict opening or closing.

Copy `web/.env.example` to `web/.env.local`, set the same secret and `CURATOR_ORIGIN=http://127.0.0.1:3000`. Open that exact origin; cookies and CSRF checks intentionally depend on it. The frontend has no public environment secrets.

Apply the committed migration, then start Python. From the repository root:

```sh
make web-migrate
make web-api
```

In another terminal:

```sh
make web-ui
```

Same thing without make:

```sh
uv run --env-file .env.web --extra web aerich upgrade
uv run --env-file .env.web --extra web uvicorn krystal_curator.web_api:app --host 127.0.0.1 --port 8100
npm run dev --prefix web
```

Open `http://127.0.0.1:3000`. The landing and `/demo` run without the Python API or database. Demo rows come from the repository fixture, use the real scoring functions, are explicitly labelled non-live, and never become real account data. Register at `/login` to use the live workspace.

## Database changes

Use Aerich via uv, never auto-create or alter production tables at application startup:

```sh
uv run --env-file .env.web --extra web aerich migrate --name describe_change
uv run --env-file .env.web --extra web aerich upgrade
```

The initial migration was generated with `uv run --extra web aerich init-db` against a disposable PostgreSQL instance. Fresh deployments apply it with `upgrade`, not `init-db`. The initial downgrade is Aerich's no-op; do not treat it as a database reset or a rollback that deletes account data. Back up the database before schema changes.

## Application behavior

- `/`: landing with original generated observatory illustration.
- `/demo`: sample screener, filters, pool details and session-only watchlist.
- `/login`: Sign-In with Ethereum (EIP-4361; wallets discovered via EIP-6963 with `window.ethereum` as fallback, custom picker; `personal_sign` of a server nonce; EOA only, no EIP-1271) or email/password registration and login, without a hosted identity service. A wallet account's monitored wallet defaults to the signing address.
- `/app`: live pool screener; profile, network and provider selection; pool details and simulation.
- `/app/watchlist`: saved pools within the selected network/profile. A saved pool filtered out by the risk profile is not deleted.
- `/app/positions`: public Krystal vault positions for the saved wallet, not standalone LP NFTs.
- `/app/leaderboard`: public vault rankings and explicit rule-based reviews.
- `/app/settings`: account-specific preferences and wallet address. Secrets/collector configuration are server-only.

Passwords use Argon2. Random sessions are stored hashed, expire after seven days and are revoked on logout. Sessions use HttpOnly / SameSite cookies, secure by default. The API derives ownership from the session, rejects client-supplied ownership fields and limits watchlists to 500 pools. Rate limits use database row locks. The Next.js bridge checks mutation origins, caps JSON bodies, and forwards only allowlisted endpoints to the private API.

Market reads reuse existing Python providers and calculations. Pool/position responses are cached for 90 seconds, leaderboard/review responses for five minutes, with source timestamps. Unknown volatility produces unknown IL/net estimates. No trade signing, Cloud credit spending, or Telegram sends happen from the web. Agent, Telegram and backtesting remain CLI features.

## Before a public deployment

- Supply `CURATOR_ORIGIN` as the exact HTTPS site origin; keep `CURATOR_COOKIE_SECURE=true`.
- Keep Python and PostgreSQL on a private network. Only Next.js should reach Python with the bridge secret.
- `CURATOR_TRUST_PROXY=true` is only for an ingress that overwrites `X-Real-IP`; otherwise the login rate limit intentionally shares one bucket. Configure an ingress body limit and connection limits as well.
- Provide `CURATOR_SOURCE_URL` for the corresponding source of the deployed revision (AGPL-3.0).
- Configure database backups and periodic removal of expired session/rate-limit rows. Session expiry is enforced regardless of cleanup.
- Email verification and password recovery are not implemented in this first slice; no email ownership is claimed and no mail is sent. These require a chosen mail delivery workflow before adding them.
- The bounded analytics cache lives in one Python process and serializes upstream refreshes. Share the cache and split locks by feed if measured traffic requires multiple workers. This version does not add a new background collector or change the existing daemon.

## Verify

```sh
uv run --extra web pytest -q
uv run --extra web ruff check src tests web/scripts
npm run build --prefix web
npm run test --prefix web
```

For real account-isolation tests, provide `CURATOR_TEST_DATABASE_URL` pointing to a **migrated disposable PostgreSQL database named `curator_test*`**:

```sh
uv run --extra web pytest tests/test_web.py -q
```

With both local servers running:

```sh
cd web
npx playwright install chromium
npm run test:browser
# Also test registration/persistence/logout against a disposable database:
CURATOR_BROWSER_ACCOUNTS=1 npm run test:browser
```

Browser checks confirm actual viewport width and no page-level horizontal overflow at 1440, 768 and 390px, and exercise watchlist, details, empty states and settings. Browser account tests create a disposable test account; discard that database after testing. Screenshots land in ignored `web/test-results/`.

Regenerate the public fixture snapshot after changing scoring:

```sh
uv run --extra web web/scripts/demo_snapshot.py
```

Architecture and asset provenance: `docs/curator-web-design.md`, `docs/curator-assets.md`. Framework reference: [Next.js Route Handlers](https://nextjs.org/docs/app/getting-started/route-handlers); migration reference: [Aerich](https://github.com/tortoise/aerich).
