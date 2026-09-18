# Curator web

Public LP analytics for liquidity providers: discover a pool, inspect evidence and save it to a private watchlist. Next.js/React frontend, thin FastAPI wrapper over existing Python analytics, local email/password authentication (Argon2, revocable cookie sessions) and PostgreSQL via Tortoise ORM + asyncpg, with Aerich migrations. No CMS; landing copy is maintained in source. Existing CLI/TUI remains compatible.

Visual thesis: an amber-lit liquidity observatory, carrying the original Bloomberg terminal's black ground, amber chrome and precise data into a spacious editorial landing and a focused web workspace. Pairs are first-class: two-token marks, a fee tier, and quote chips — the list reads as two sides of a pool, not a ticker string.

Tokens: background #080909, surface #111211, foreground #e8e5dc, muted #a3a59c, accent #ff9a00, line #30332c. Display uses a heavy system sans; data and labels use system monospace. Rectangular panels, restrained amber borders, a 4/8px spacing rhythm, large readable landing typography. Motion only for interaction feedback; respect reduced motion.

One original amber/black observatory illustration, right side of hero, no mascot or embedded text. Mobile crops retain the central instrument; HTML proposition and CTA precede artwork. Critical application controls have quiet backgrounds.

Routes: / landing, /login email/password, /demo explicitly labelled fixture snapshot, /app screener and watchlist, /app/positions, /app/leaderboard, /app/settings. Pool detail is a responsive panel. Agent, Telegram and backtesting retain existing CLI support.

Live data includes source and fetch timestamp; fixture data is always labelled demo and does not impersonate a signed-in user. Unknown numeric metrics are null at the HTTP boundary. No wallet signing or trade execution. The Python API and migrated PostgreSQL database are required for real accounts; failure to configure them must never activate an authentication bypass.
