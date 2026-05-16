# WARP•FORGE REPORT — webtrader-dashboard

Branch: WARP/CRUSADERBOT-WEBTRADER
Date: 2026-05-16 21:00 Asia/Jakarta
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: /dashboard frontend + /api/web/* backend + SSE LISTEN/NOTIFY listener + migration 029
Not in Scope: live trading path, ENABLE_LIVE_TRADING guards, wallet sweep, Telegram bot, existing /ops, /health, /admin routes

---

## 1. What Was Built

Browser-based WebTrader dashboard at /dashboard for CrusaderBot users to monitor and configure
their auto-trade strategy in real-time. Authentication via Telegram Login Widget + JWT (HS256).
Realtime updates via SSE backed by PostgreSQL LISTEN/NOTIFY.

Components:

**Backend (projects/polymarket/crusaderbot/webtrader/backend/)**
- auth.py: Telegram Login Widget hash validation (SHA256 key, HMAC-SHA256 verify) + PyJWT HS256 issuance
- sse.py: Dedicated asyncpg LISTEN connection (bypasses pooler) + per-user asyncio.Queue fan-out
- router.py: FastAPI APIRouter at /api/web/* — 13 routes
- schemas.py: Pydantic v2 models for all request/response shapes

**Frontend (projects/polymarket/crusaderbot/webtrader/frontend/)**
- React 18 + Vite 5 + TypeScript + Tailwind CSS 3
- 6 pages: Auth, Dashboard, Auto Trade, Portfolio, Wallet, Settings
- 7 components: TelegramAuth, BottomNav, PnLCard, PositionTable, StrategyCard, CustomizeDrawer, KillSwitchButton
- 3 lib modules: auth.ts (React Context, memory-only JWT), api.ts (typed fetch wrapper), sse.ts (useSSE hook)

**Migration (migrations/029_webtrader_tables.sql)**
- portfolio_snapshots table (time-series equity/PnL per user)
- system_alerts table (operator-pushed broadcast alerts)
- NOTIFY trigger functions on 7 tables + trigger bindings

**Integration**
- main.py: SSE listener started in lifespan, web_router included, static mount, root redirects to /dashboard
- Dockerfile: multi-stage (Node 20 frontend build + Python 3.11 app)

---

## 2. Current System Architecture

```
Browser (mobile-first, 430px, dark theme)
  → /auth: Telegram Login Widget → POST /api/web/auth/telegram → JWT (memory only)
  → /dashboard/*: React Router + Tailwind pages
  → GET /api/web/stream?token=<jwt>: SSE (EventSource auto-reconnect)

FastAPI (main.py)
  → APIRouter at /api/web/*  (auth.py dependency: Bearer token or ?token= query param)
  → StaticFiles at /dashboard (webtrader/frontend/dist/)

SSE Subsystem
  → sse.py: dedicated asyncpg.connect() (direct Postgres, NOT pooler)
  → LISTEN cb_orders|cb_fills|cb_positions|cb_user_settings|cb_system_settings|cb_portfolio|cb_alerts
  → _user_queues: dict[str, list[asyncio.Queue]] — routes pg_notify to connected users
  → stream_for_user(): async generator → sse-starlette EventSourceResponse

PostgreSQL (Supabase)
  → Trigger functions fire pg_notify on INSERT/UPDATE to key tables
  → LISTEN/NOTIFY requires direct connection (port 5432), not pooler (port 6543)

Fly.io deploy
  → Dockerfile: Stage 1 npm ci + vite build, Stage 2 python + COPY --from=frontend-build
  → VITE_BOT_USERNAME passed as --build-arg at deploy time
  → WEBTRADER_JWT_SECRET set via fly secrets set
```

---

## 3. Files Created / Modified

### New files

```
projects/polymarket/crusaderbot/
  migrations/029_webtrader_tables.sql
  webtrader/__init__.py
  webtrader/backend/__init__.py
  webtrader/backend/schemas.py
  webtrader/backend/auth.py
  webtrader/backend/sse.py
  webtrader/backend/router.py
  webtrader/frontend/package.json
  webtrader/frontend/package-lock.json
  webtrader/frontend/tsconfig.json
  webtrader/frontend/vite.config.ts
  webtrader/frontend/tailwind.config.ts
  webtrader/frontend/postcss.config.js
  webtrader/frontend/index.html
  webtrader/frontend/src/vite-env.d.ts
  webtrader/frontend/src/index.css
  webtrader/frontend/src/main.tsx
  webtrader/frontend/src/App.tsx
  webtrader/frontend/src/lib/auth.ts
  webtrader/frontend/src/lib/api.ts
  webtrader/frontend/src/lib/sse.ts
  webtrader/frontend/src/components/TelegramAuth.tsx
  webtrader/frontend/src/components/BottomNav.tsx
  webtrader/frontend/src/components/PnLCard.tsx
  webtrader/frontend/src/components/PositionTable.tsx
  webtrader/frontend/src/components/StrategyCard.tsx
  webtrader/frontend/src/components/CustomizeDrawer.tsx
  webtrader/frontend/src/components/KillSwitchButton.tsx
  webtrader/frontend/src/pages/AuthPage.tsx
  webtrader/frontend/src/pages/DashboardPage.tsx
  webtrader/frontend/src/pages/AutoTradePage.tsx
  webtrader/frontend/src/pages/PortfolioPage.tsx
  webtrader/frontend/src/pages/WalletPage.tsx
  webtrader/frontend/src/pages/SettingsPage.tsx
  reports/forge/webtrader-dashboard.md
```

### Modified files

```
projects/polymarket/crusaderbot/
  main.py           — SSE lifespan task, web_router include, static mount, root redirect
  pyproject.toml    — added sse-starlette>=1.6, PyJWT>=2.8
  config.py         — added WEBTRADER_JWT_SECRET: Optional[str] = None
  Dockerfile        — multi-stage with Node 20 frontend build
  state/PROJECT_STATE.md
  state/CHANGELOG.md
```

---

## 4. What Is Working

- TypeScript compiles clean (tsc --noEmit: zero errors)
- Frontend builds clean: vite build produces dist/ (190KB JS, 12KB CSS)
- Backend Python syntax verified: py_compile on all 4 backend modules passes
- Migration 029 is idempotent (CREATE OR REPLACE + DROP TRIGGER IF EXISTS)
- SSE URL normalization: pooler.supabase.com → db.{project_ref}.supabase.co, port 6543 → 5432
- JWT auth: verify_telegram_hash uses SHA256(BOT_TOKEN) as HMAC key per Telegram spec
- Kill switch endpoint reuses domain.ops.kill_switch.set_active (same path as /ops/kill)
- Root GET / redirects 302 to /dashboard
- Activation guards untouched: ENABLE_LIVE_TRADING remains false

---

## 5. Known Issues

- SENTINEL required before merge (MAJOR tier)
- BotFather domain registration pending (WARP🔹CMD): /setdomain @CrusaderBot crusaderbot.fly.dev — Telegram Login Widget will not render without this
- WEBTRADER_JWT_SECRET must be set as Fly.io secret before deploy: fly secrets set WEBTRADER_JWT_SECRET=$(openssl rand -hex 32)
- Migration 029 must be applied to production before deploy
- JWT in memory only — page refresh requires re-auth (intentional per spec)
- cb_fills NOTIFY payload has no user_id; SSE layer resolves via async orders JOIN (1 extra DB query per fill event)
- user_settings.notifications_on column does not exist in current schema — SettingsPage GET returns defaults gracefully; PATCH is a no-op until column is added
- Fly.io VITE_BOT_USERNAME must be passed at build time: fly deploy --build-arg VITE_BOT_USERNAME=CrusaderBot
- Supabase direct connection URL (port 5432) must be reachable from Fly.io VM for LISTEN/NOTIFY to work; if only pooler URL is in DATABASE_URL, pg_notify will be silently dropped

---

## 6. What Is Next

- WARP•SENTINEL audit (MAJOR) — validate SSE fan-out, JWT auth, kill switch path, DB query safety
- WARP🔹CMD: set WEBTRADER_JWT_SECRET fly secret, register BotFather domain, fly deploy
- Apply migration 029 to production (after 027 and 028)
- Add portfolio_snapshots population: scheduler job to INSERT snapshot every hour per user
- Add user_settings.notifications_on column (migration 030) to enable settings toggle
- SENTINEL-approved PR merge + smoke test at crusaderbot.fly.dev

---

Suggested Next Step: WARP•SENTINEL validation of webtrader-dashboard (MAJOR tier).
