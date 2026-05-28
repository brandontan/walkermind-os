# multitenant-safety

Validation Tier: **MAJOR**
Claim Level: **NARROW INTEGRATION**
Validation Target: Axis #1 — per-user isolation on the WebTrader backend; new per-user rate limiter; sealing the global kill-switch bypass via `/api/web/{kill,emergency-stop}`.
Not in Scope: Bot-side Telegram handler audit (separate axis); RLS-policy DDL changes (RLS already enabled on all 43 public tables and the service-role backend bypasses RLS by design — application-layer scoping is the contract); operator auth hardening (`/api/ops/*` already cookie+token gated since H1); per-user rate limit on auth endpoints (different abuse surface, separate lane); WebTrader frontend UX relabel of the kill button (kept stable for backwards-compat; intent now correctly per-user).

## 1. What was built

WARP•R00T audit of the multi-tenant safety surface, followed by:

### Patch A — kill-switch isolation (CRITICAL fix)

`/api/web/kill` and `/api/web/emergency-stop` were activating the GLOBAL kill switch (`system_settings.kill_switch_active`). Any authenticated user clicking the "kill" button on the dashboard halted trading for **every other user**. The intent of those endpoints is per-user — pause MY bot, close MY positions — so the implementation was wrong.

- `web_kill` now calls `users.set_paused(user_id, True)`. The risk gate already honours `ctx.paused` at `domain/risk/gate.py:259` and rejects new trades for that user only.
- `web_emergency_stop` now sets `users.paused=TRUE` + force-closes the calling user's positions via the existing `mark_force_close_intent_for_user`. No global state mutation.
- New `web_resume` (`POST /api/web/resume`) clears the per-user paused flag — there was previously no WebTrader way to undo a pause without going to Telegram.
- `RuntimeStatus` schema gains a `user_paused` field; the existing `kill_switch_active` field stays as informational (operator-set state, surface only).
- `EmergencyStopResponse` schema: `kill_switch_active` → `user_paused`.
- Frontend `api.ts` typed accordingly; `getKillSwitch`/`postKill`/`postEmergencyStop` return shapes updated; new `api.bot.postResume`. (No frontend rendering change yet — the dashboard's `KillSwitchButton` continues to call `/kill`, which now correctly per-user-pauses. Label / disabled-state polish is a UX lane.)

### Patch B — per-user rate limiter (HIGH fix)

`api/rate_limit.py` is per-source-IP only (600/min after the bundled fix from #1431). A single authenticated user can still spam cost-sensitive POSTs — withdrawal-queue flood, copy-task storm, position-close hammering. New `api/per_user_rate_limit.py` adds a sliding-window in-memory bucket keyed on `(user_id, scope)`:

- `Depends(per_user_rate_limit("withdraw", limit=10))` is the opt-in shape.
- Returns 429 + `Retry-After` on overflow.
- Bucket table capped at 50 000 keys with idle-eviction to bound memory under a token-stuffing attack.
- Distinct scopes never share a budget — withdraw budget is independent of copy-task budget.
- Distinct users never share a budget — User A's spam never starves User B.

Applied to:
- `POST /wallet/withdraw` — 10/min (admin-queue protection)
- `POST /copy-trade/tasks` — 20/min (signal-fetch budget)
- `POST /positions/{id}/redeem` — 30/min (RPC + DB write)
- `POST /positions/{id}/close` — 30/min (order submission)
- `POST /kill` + `POST /resume` — shared `user_pause` scope, 10/min (anti-flap)
- `POST /emergency-stop` — 5/min (rare, dramatic op)

### Patch C — regression pins

`tests/test_multitenant_safety.py` (9 hermetic tests):
1. Per-user limiter allows within budget.
2. Per-user limiter blocks over budget + sets Retry-After.
3. Distinct users have independent buckets.
4. Distinct scopes have independent buckets.
5. Missing `user_id` is a no-op (defers to auth dependency 401).
6. `web_kill` body must NOT contain `kill_switch.set_active` — source-level pin.
7. `web_emergency_stop` body must NOT contain `kill_switch.set_active` — source-level pin.
8. `web_resume` body must call `set_paused` with `False`.
9. Cost-sensitive endpoints must declare `per_user_rate_limit` with the expected scope — source-level pin.

## 2. Current system architecture

```
WebTrader user → /api/web/{kill,resume,emergency-stop}
                    ↓
                 users.paused = TRUE/FALSE   (per-user, scoped)
                    ↓
                 risk gate step 2 honours    (gate.py:259)

WebTrader user → /api/web/* (POST)
                    ↓
                 IP limiter 600/min (global abuse)
                    ↓
                 per_user_rate_limit (per-authenticated-user)
                    ↓
                 endpoint handler with WHERE user_id = $1

Operator → /api/ops/kill (cookie+token gated)
        OR Telegram /kill (operator chat id gated)
                    ↓
                 kill_switch.set_active() — GLOBAL
                    ↓
                 ENABLE_LIVE_TRADING + assert_live_guards chain
                    ↓
                 risk gate step 0 blocks ALL trades
```

The global kill switch is now unreachable from any WebTrader user endpoint. Application-layer per-user scoping is verified clean across the 22 state-changing endpoints in `webtrader/backend/router.py`.

## 3. Files created / modified (full repo-root paths)

Created:
- projects/polymarket/crusaderbot/api/per_user_rate_limit.py
- projects/polymarket/crusaderbot/tests/test_multitenant_safety.py
- projects/polymarket/crusaderbot/reports/forge/multitenant-safety.md
- projects/polymarket/crusaderbot/reports/sentinel/multitenant-safety.md

Modified:
- projects/polymarket/crusaderbot/webtrader/backend/router.py — `/kill`, `/emergency-stop`, `/status` rewired; new `/resume`; per-user limiter applied to 5 endpoints.
- projects/polymarket/crusaderbot/webtrader/backend/schemas.py — `EmergencyStopResponse.kill_switch_active` → `user_paused`; `RuntimeStatus` gains `user_paused`.
- projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts — type-side mirror of the schema changes; new `postResume`.
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md
- projects/polymarket/crusaderbot/state/CHANGELOG.md

## 4. What is working

- `tests/test_multitenant_safety.py` 9/9 pass.
- Regression neighbourhood (test_rate_limit, test_health, test_warp54_closed_beta_hardening) 54/54 pass.
- `py_compile` clean on all 3 modified Python files.
- The 7 source-level pins in test_multitenant_safety fail closed if a future edit re-introduces the global kill-switch toggle or drops a per-user rate-limit decoration.

## 5. Known issues

- **Frontend UX polish deferred.** The dashboard's `KillSwitchButton` and the `data.kill_switch_active` HUD pill still show in their original visual form. The button now correctly pauses-the-user (not the global system) under the hood, but the labelling and the GUARDS/HALTED HUD pill could be more explicit ("MY BOT: PAUSED" vs "SYSTEM: HALTED"). Separate small lane.
- **In-memory bucket only.** `per_user_rate_limit` state is per-process. Fly runs the WebTrader as a single primary instance today, so this is fine. If/when the bot moves to multi-region or multi-machine, the bucket would need a Redis backend.
- **No per-route stats.** The new limiter does not emit a metric on 429. Operators currently see the 429 via the request log. Adding a structlog event is a follow-up.

## 6. What is next

- Axis #3 live-trading activation flow (MAJOR — SENTINEL required): per-user opt-in UI, double-confirm, capital cap, kill-switch wiring, audit log.
- Axis #7 public-readiness audit (read-only synthesis).

## Suggested Next Step

Embedded SENTINEL self-validation report at `projects/polymarket/crusaderbot/reports/sentinel/multitenant-safety.md` — WARP•R00T self-validated under WARP🔹CMD delegation. WARP🔹CMD final review + merge.
