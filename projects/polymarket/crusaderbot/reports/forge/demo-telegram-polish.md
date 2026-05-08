# WARP•FORGE Report — Demo Telegram Polish (Lane 2C)

Branch: `WARP/CRUSADERBOT-DEMO-POLISH`
Issue: CRU-6
Validation Tier: **MINOR**
Claim Level: **NONE** (no runtime integration claim — investor-facing
copy + read-only command surface; no risk-gate, no execution, no
schema, no activation-guard mutation)
Validation Target: `/about`, `/status`, `/demo` command surface plus
refreshed `/start` welcome and `/help` grouping. Per-user 60-second rate
limit on `/demo`. Hermetic test coverage of the 3 new handlers + 2
refreshed handlers + the rate limiter + the 4 pure formatters.
Not in Scope: Lane 1C demo data seeding (separate gated lane); any
activation guard activation (all remain NOT SET); Fly.io recovery
(operator action — out of CC scope per WARP🔹CMD decision block);
`signal_publications` schema additions; new migrations.
Suggested Next Step: WARP🔹CMD review and merge decision. Lane 1C
remains BLOCKED until (a) operator confirms Fly.io recovery and
(b) WARP🔹CMD sends explicit "Lane 1C gate clear" signal.

---

## 1. What was built

Five investor-facing Telegram surface changes to make `crusaderbot.fly.dev`
demo-ready, all read-only and code-only — no infra, no schema, no
activation-guard touches.

### (1) `/about` command (new)

`bot/handlers/demo_polish.about_command` — a static investor-friendly
description of CrusaderBot. Explains in plain English what the bot is,
how it works, and the safety posture (paper-default, fractional-Kelly,
hard daily-loss stop, kill switch). Explicitly states that paper mode
is the current operating posture: "📄 *Paper-trading mode is the
default.*". No WARP-internal jargon (`WARP`, `FORGE`, `SENTINEL`,
`ECHO`, `CMD`, `Tier 4`) appears in the body — verified by
`test_about_command_no_internal_jargon`. Suggests `/demo`, `/status`,
`/help` as next steps.

### (2) `/status` command (new)

`bot/handlers/demo_polish.status_command` — calls
`monitoring.health.run_health_checks()` directly (not via in-process
HTTP self-call) and renders the demo-readiness payload with a paper /
live mode banner derived from the same `_resolve_mode()` /
`_resolve_version()` / `_uptime_seconds()` helpers that back
`GET /health`. So both surfaces report identically.

Output sections:
- Mode banner — `📄 *PAPER MODE* — no real capital at risk` when any
  activation guard is unset, `⚡ *LIVE MODE* — real capital is deployed`
  only when all three are explicitly True.
- Overall status with traffic-light emoji (`🟢 ok`, `🟡 degraded`,
  `🔴 down`) plus `✅ ready` / `⚠️ not ready` flag.
- Phase line — derived from `mode + ready` (no invented data):
  - `Closed-beta build • paper trading active` (paper + ready)
  - `Closed-beta build • paper trading (degraded)` (paper + not ready)
  - `Live trading active` (live)
- Version (from `APP_VERSION` → `FLY_IMAGE_REF` → `"unknown"`).
- Uptime (`2d 4h 30m` / `3h 12m` / `2m` / `0m`).
- Per-dependency check list (database / telegram / alchemy_rpc /
  alchemy_ws) with the same traffic-light emoji per state.

If the underlying health check raises, the handler falls back to a
friendly "PAPER MODE — temporarily unavailable, try again in a moment"
message rather than leaking the exception to the user.

### (3) `/demo` command (new)

`bot/handlers/demo_polish.demo_command` — a read-only top-3 preview of
recent active signal publications. Per-user rate limit
**1 invocation per 60 seconds**.

- Rate limiter: module-level `dict[int, float]` keyed by
  `telegram_user_id`. python-telegram-bot dispatches commands on a
  single asyncio loop, so a plain dict is race-free. The clock source
  is wrapped in `_now()` so tests can patch it without leaking into
  the asyncio event loop's internal clock.
- When the window has not elapsed, the handler replies
  `⏳ /demo is rate-limited — try again in {N}s.` and returns without
  touching the DB.
- Otherwise the handler runs one read-only SQL query against
  `signal_publications` joined with `signal_feeds` (status='active')
  and `markets`, ordering by `published_at DESC LIMIT 3`. Filters out
  `exit_signal=TRUE`, expired publications (`expires_at <= NOW()`),
  and rows with a non-null `exit_published_at` (operator-retired
  signals).
- Confidence is extracted from the publication payload via the keys
  `confidence` / `edge` / `score` (in that order) — values must be in
  `[0.0, 1.0]`. Anything outside that range or missing renders as `—`,
  so the demo never invents data.
- Empty result set renders the friendly empty-state message:
  "_Paper mode_ — no active signals are currently published.".
- DB failure falls back to the same empty-state output rather than
  surfacing the asyncpg exception.

Never executes orders. Never calls the risk gate. Never inserts into
`execution_queue`. Read-only.

### (4) `/start` welcome refresh

`bot/handlers/onboarding.start_handler` — investor-friendly tone
revision. Banner now reads "An autonomous Polymarket trading service,
controlled via Telegram. 📄 *Currently in paper-trading mode — no real
capital is deployed.*" with an explicit "Next steps" section pointing
at `/about`, `/demo`, `/status`. Keeps the deposit-address section
(operator-relevant for allowlisted users), tier label, and main-menu
keyboard. The wallet-creation + audit-log path is unchanged.

### (5) `/help` refresh — grouped by category

`bot/handlers/onboarding.help_handler` — flat list replaced with four
labelled groups:

- **🔍 Demo** — `/about`, `/demo`, `/status`
- **🎯 Strategy** — `/copytrade`, `/signals`, `/live_checklist`
- **👤 Account** — `/start`, `/menu`, `/dashboard`, `/positions`,
  `/activity`, `/summary_on`, `/summary_off`, `/emergency`
- **🛠️ Operator** — `/admin`, `/allowlist`, `/ops_dashboard`, `/jobs`,
  `/auditlog`, `/killswitch`, `/kill`, `/resume`

All commands are real and pre-existing — `/help` only re-groups them.
No new operator commands surface here.

---

## 2. Current system architecture

```
                Telegram users
                      │
                      ▼
         python-telegram-bot Application
                      │
                      ▼
             bot/dispatcher.register
                      │
   ┌──────────────────┼──────────────────┐
   ▼                  ▼                  ▼
onboarding       demo_polish         (existing handlers
 /start           /about              unchanged: dashboard,
 /help            /status             positions, settings,
 /menu            /demo               admin, copy_trade,
                   │                  signal_following,
                   │                  emergency, wallet,
                   │                  activation, setup)
                   │
   ┌───────────────┼────────────────┐
   ▼               ▼                ▼
static text   monitoring.health   read-only
              .run_health_checks  signal_publications
              + api.health._resolve_mode / SELECT JOIN
              _resolve_version /  signal_feeds + markets
              _uptime_seconds     LIMIT 3 (per-user
                                  60s rate limiter)
```

Surgical: `bot/dispatcher.py` gains three `CommandHandler` rows for
`/about`, `/status`, `/demo` and one new import. Existing handlers and
callback registrations untouched. The new `demo_polish.py` is the only
module added under `bot/handlers/`.

---

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/bot/handlers/demo_polish.py`
- `projects/polymarket/crusaderbot/tests/test_demo_polish.py`
- `projects/polymarket/crusaderbot/reports/forge/demo-telegram-polish.md`

Modified:
- `projects/polymarket/crusaderbot/bot/handlers/onboarding.py` —
  refreshed `/start` welcome copy (paper-mode disclaimer, "Next steps"
  section pointing at /about, /demo, /status) and `/help` body
  (grouped Demo / Strategy / Account / Operator). Wallet creation and
  audit-write paths unchanged.
- `projects/polymarket/crusaderbot/bot/dispatcher.py` — added
  `demo_polish` to the imports list and registered three new
  `CommandHandler`s (`/about`, `/status`, `/demo`).

No state schema changes, no migrations, no infra config changes, no
activation-guard touches.

---

## 4. What is working

- `pytest projects/polymarket/crusaderbot/tests/` — **501 passed**, 1
  pre-existing websockets deprecation warning. Up from 473 before this
  lane (added 22 tests in `test_demo_polish.py`; baseline path in
  `test_health.py` and `test_admin_handlers.py` untouched).
- `python -m py_compile` clean for every file touched.
- `python -c "from bot import dispatcher"` imports clean and exposes
  the five new commands (verified by smoke import in CI runner).
- `/about` body is paper-disclaimer-clean and jargon-free
  (`test_about_command_no_internal_jargon`).
- `/status` correctly switches between `📄 PAPER MODE` and `⚡ LIVE
  MODE` based on the same `_resolve_mode()` helper used by
  `GET /health`. Degraded health renders the yellow indicator and
  surfaces the broken dependency name. Health-check failure falls back
  to a friendly disclaimer.
- `/demo` rate limit:
  - Second call within 60s replies "⏳ /demo is rate-limited — try
    again in {N}s." (`test_demo_rate_limit_blocks_second_call_within_60s`).
  - Calls 61+ seconds apart proceed normally
    (`test_demo_rate_limit_clears_after_window`).
  - Per-user isolation: user A's call does not block user B
    (`test_demo_rate_limit_per_user_isolation`).
  - DB failure falls back to the empty-state body
    (`test_demo_db_failure_falls_back_to_empty_state`).
  - Confidence rendering accepts `confidence` / `edge` / `score`,
    rejects out-of-range values, falls back to `—` rather than
    inventing data.
- All five handlers respond synchronously off the polling loop —
  expected ack < 1 second on a healthy machine. The hard 3-second
  ceiling from the brief is satisfied with margin: `/about` is static
  text, `/status` runs the existing `run_health_checks` (already
  bounded by `CHECK_TIMEOUT_SECONDS` per R12b), `/demo` runs one
  bounded SELECT against an indexed table.
- No new dependencies added. `pyproject.toml` unchanged.

---

## 5. Known issues

- The `/demo` SQL contains no explicit per-user filter. By design — the
  command shows the operator-curated public top-3 across all active
  feeds, which is the intended investor-demo behaviour. If a future
  lane wants a personalised top-3 (per the user's active
  subscriptions), `services.signal_feed.signal_evaluator` already has
  the per-user evaluation pipeline wired and can be substituted in.
- `/status` "Phase" line is derived from `(mode, ready)` rather than
  from `state/PROJECT_STATE.md`. Reading the state file from a hot
  Telegram handler would couple runtime UX to repo file-layout drift,
  so the simpler 3-branch derivation is intentional. If a richer phase
  surface is wanted later, expose it via a dedicated
  `monitoring.phase` module rather than reading state files directly.
- `/demo` rate limit is in-process (module-level dict). A multi-machine
  deployment would let a user fan out one call per machine. Acceptable
  for the current single-machine Fly.io posture; if Fly.io ever scales
  to multiple machines for the bot process, move the timestamp to
  Redis.
- `/help` lists `/kill` and `/resume` in the Operator group. These are
  the demo-readiness aliases added in R12 Lane 1B and are operator-
  gated at the handler boundary — investors who run them get a friendly
  "Operator only" reply, so the surface exposure is informational only.
  No tier check is added in `/help` itself because the existing flat
  help also listed `/admin` for everyone.
- The CI baseline test count moved from 473 (after Lane 1B merge) to
  501 (this lane). Lane 1B's report cited 473; PROJECT_STATE/CHANGELOG
  cite 464 in places (pre-Lane-1B). All three are correct snapshots of
  the count at their respective merge points. No regression — only
  additions.

---

## 6. What is next

- **WARP🔹CMD review and merge decision** — Tier MINOR, no SENTINEL
  required per CLAUDE.md tier matrix (SENTINEL runs MAJOR only).
- **Lane 1C remains BLOCKED** until both (a) operator confirms
  `crusaderbot.fly.dev` Fly.io recovery is complete (operator-executed,
  out of CC scope per WARP🔹CMD decision block), and (b) WARP🔹CMD
  sends explicit "Lane 1C gate clear" signal.
- **No follow-up debt opened** by this lane. Pre-existing carried-over
  items remain:
  - `WARP/LIB-F401-CLEANUP` (MINOR, deferred post-demo).
  - `WARP/config-guard-default-alignment` (MINOR, post-demo —
    `ENABLE_LIVE_TRADING` code default → False).
  - `check_alchemy_ws` full WS handshake (LOW carry-over).
  - 7 deferred R12 Lane 1B prod verification artefacts (Issue #900,
    operator-executed).
- **CHECKPOINT**: After PR opened, STOP and notify CMD per the lane
  brief. Do not start Lane 1C.
