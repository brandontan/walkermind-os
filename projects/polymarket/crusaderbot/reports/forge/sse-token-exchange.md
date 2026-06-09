# WARP•R00T FORGE REPORT — sse-token-exchange

Branch: WARP/ROOT/sse-token-exchange
Date: 2026-05-30 01:16 Asia/Jakarta
Lane: 3b/5 of the WARP•R00T full-system pre-public-ready audit fix campaign

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : the main 24h JWT never appears in the SSE URL; the stream authenticates via a short-lived SSE-scoped token; a leaked stream token cannot call the API
Not in Scope      : JWT TTL/revocation on the main token; CORS/security-headers; Lanes 4 + 5
Suggested Next    : WARP•SENTINEL (auth surface), then Lane 4 (tg-callback-routing)

## 1. What was built
Closes audit finding B2: `EventSource` cannot send an `Authorization` header, so
the WebTrader streamed the full 24h JWT in the URL (`/api/web/stream?token=<JWT>`)
— which lands in Fly/Uvicorn/proxy access logs and browser history. A logged JWT
is a 24h account credential.

Fix — short-lived token exchange:
- New authenticated `POST /api/web/stream-token` mints a JWT with `scope:"sse"`
  and a 60s TTL (`auth.mint_stream_token`).
- `GET /api/web/stream` no longer authenticates via the main JWT
  (`_CurrentUser`); it validates only the scoped handshake token
  (`auth.decode_stream_token`, which enforces `scope=="sse"`).
- `get_current_user` now REJECTS any `scope=="sse"` token (401), so a leaked
  stream token cannot be replayed against the API.
- Frontend `lib/sse.ts` `connect()` is now async: it `POST`s `/stream-token`
  with the Bearer JWT, then opens `EventSource` with the 60s token; a fresh
  token is minted on every (re)connect, with backoff on mint failure.

Net: even if a stream URL is logged, the token is useless within 60s and can
never authenticate an API call.

## 2. Current system architecture (relevant slice)
Auth handshake: browser holds the main JWT (localStorage) → `POST /stream-token`
(Bearer) → 60s `sse`-scoped token → `EventSource('/api/web/stream?token=<sse>')`
→ `decode_stream_token` (scope-checked) → `webtrader_sse.stream_for_user(user_id,
telegram_id)`. The main JWT stays in the `Authorization` header on every other
call and never touches a URL.

## 3. Files created / modified (full repo-root paths)
Modified:
- projects/polymarket/crusaderbot/webtrader/backend/auth.py (mint_stream_token + decode_stream_token + sse-scope reject in get_current_user)
- projects/polymarket/crusaderbot/webtrader/backend/router.py (POST /stream-token; /stream validates scoped token; Query + auth imports)
- projects/polymarket/crusaderbot/webtrader/frontend/src/lib/sse.ts (async connect: mint handshake token, refresh per reconnect)
Created:
- projects/polymarket/crusaderbot/tests/test_sse_token_exchange.py (7 tests)

## 4. What is working
- py_compile + ruff clean; tsc --noEmit + vite build clean.
- 7/7 Lane tests pass (mint scope+TTL, decode accept/reject/missing, API rejects
  sse token, API accepts normal token, source-pin sse_stream auth path).
- 22 existing auth/account-link tests still pass (no regression).

## 5. Known issues
- Atomic deploy serves new frontend + backend together; browser tabs still
  running the OLD cached JS would pass the main JWT to /stream and now get 401 →
  SSE drops until refresh (dashboards have a 15s polling fallback, so data stays
  fresh). Self-heals on reload.
- Main JWT TTL/revocation (24h) is a separate tracked audit item — not in scope.

## 6. What is next
- WARP•SENTINEL (auth surface) — MAJOR.
- Lane 4: WARP/ROOT/tg-callback-routing. Lane 5: WARP/ROOT/live-path-hardening.

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
