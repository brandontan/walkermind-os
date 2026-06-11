# live-golive-handoff — deposit-watcher root-cause handoff

Role: WARP•R00T | Branch: WARP/root-live-golive-handoff | 2026-06-11 ~15:10 Asia/Jakarta
Origin: continued live go-live support after the overnight readiness program (all lanes merged). Owner is activating live trading from mobile; blocked on the Enable-Live-Trading modal gate 4 ("Wallet funded — at least one confirmed USDC deposit").

## Objective
Flip gate 4 for the owner's account so live trading can be enabled. Gate 4 = `COUNT(deposits WHERE user_id=$1 AND confirmed_at IS NOT NULL) > 0` (`domain/activation/live_checklist.py` `_gate_active_subaccount`). No amount check — any one confirmed deposit row satisfies it.

## State at handoff (prod Supabase `ykyagjdeqcgcktnpdhes`, read-only)
- `chain_cursor.usdc_deposits` = block 0 (updated_at ~36 days stale — never advanced)
- `chain_cursor.usdc_native_deposits` = block 0 (~2 days stale)
- `deposits` table = 0 rows
- `wallets` = 6 total; all 6 have `deposit_address`; 0 have `safe_address`; 0 have `polymarket_deposit_wallet`
- Owner's $8.32 deposit landed on their Polymarket proxy/deposit wallet (= `polymarket_deposit_wallet`, currently NULL → NOT in the watcher's watch set)
- Global LIVE guards are OPEN (ENABLE_LIVE_TRADING + 4 others + USE_REAL_CLOB true via Fly secrets); **0 users in live mode** → nothing actually trades. Two-layer gate intact.

## What got fixed today
1. **RPC restored** — `POLYGON_RPC_URL` now points to a working Alchemy Polygon endpoint (verified externally: HTTP 200 / chainId `0x89`; Alchemy dashboard shows live traffic ~4.5 CU/s, "just now"). The earlier deposit-watcher failures were a stale/broken RPC value.
2. **Scheduler un-wedged** — trading scans (`scan_runs`) ran every ~2-3 min until **06:12 UTC**, then stopped dead for ~1.5h while uvicorn stayed up (admin console + Alchemy traffic still live). A Fly **app restart** cleared it: `scan_runs` resumed (6 runs / 10 min, newest 33s after the restart). Root pattern: every APScheduler job is `max_instances=1`; a job that hangs on a no-timeout network call freezes the queue behind it.

## What is STILL blocking gate 4 (in order)
1. **Deposit watcher frozen 36 days.** Even after the restart AND with RPC confirmed working, `chain_cursor.usdc_deposits` stays block 0. Every `watch_deposits` tick (120s) bails at one of two early returns: head read (`scheduler.py:251-254`, `polygon.latest_block`) or scan (`scheduler.py:258-264`, `polygon.scan_from_cursor` → `eth_getLogs`). On a SUCCESSFUL tick the cursor MUST advance off 0 (`scheduler.py:282-283`), so it is failing, not idle.
   - **NEXT ACTION:** capture the `watch_deposits DOWN — ... stage=<head read|scan> err=<exc>` line (`scheduler.py:204`) from Fly Live Logs (filter `watch_deposits`) or Sentry (escalates to ERROR after 3 consecutive fails, `scheduler.py:200`). The `stage` pinpoints the failing call. Other Polygon calls (balance reads, redeem) succeed, so this is watcher-path-specific — most likely an `eth_getLogs` shape/range issue at the scan stage. Likely a one-file R00T patch to `integrations/polygon.py`.
2. **`polymarket_deposit_wallet` NULL ×6.** The owner's actual deposit address isn't in the watch set. ACTION: tap WebTrader admin → Maintenance → "Backfill deposit wallets" (`POST /api/web/admin/backfill-deposit-wallets`) once the SDK Polygon path is confirmed reachable. (An earlier tap skipped all 6 — the resolver couldn't reach Polygon at that time.)
3. **Lookback window.** `DEPOSIT_SCAN_LOOKBACK_BLOCKS=50_000` (~28h); cold-start scans `head-50k` forward, 1000 blocks per 120s tick (~100 min to reach head). The $8.32's block must be within the window AND its address backfilled BEFORE the cursor walks past it. Cleanest path: confirm watcher healthy → backfill → then a FRESH deposit (recent block, caught fast) rather than racing to catch the old one. (`DEPOSIT_CONFIRMATION_DEPTH=32` ≈ ~1 min to confirm once seen.)

## Notes / non-blockers
- `MIN_DEPOSIT_USDC=50` does NOT gate the deposit-recording path (`_record_pending_deposit`, `scheduler.py:325` records any amount) → $8.32 CAN satisfy gate 4. The $50 floor only affects actual trading later; $8.32 is too small to trade meaningfully, so the owner may prefer a ≥$50 deposit regardless.

## Root-cause follow-up lane (after unblock)
Harden background jobs against the wedge that caused today's 06:12 stall: add an explicit request timeout to the Polygon `AsyncHTTPProvider` (`integrations/polygon.py` `_get_w3`) and/or a per-job watchdog, so a single hung network call cannot strand the whole scheduler (and silently stop deposit crediting). Tier: MAJOR (scheduler/infra) — would warrant inline SENTINEL.

## Constraints (unchanged — must persist)
- HARD STOP: no real fund movement / live order placement by the agent — the real-money switch is the owner's.
- Never weaken risk constants, the non-custodial boundary, or the two-layer live gate.
- Never echo/commit the Alchemy API key — reference by env-var name only.

## Key file refs
- `scheduler.py:216` watch_deposits; `:251-254` head-read return; `:258-264` scan return; `:282-283` cursor write; `:325` _record_pending_deposit; `:195` _watch_deposits_failed (escalation).
- `integrations/polygon.py:136` latest_block; `:161-215` scan_usdc_transfers (eth_getLogs); `:218-237` scan_from_cursor (cold-start lookback).
- `config.py:530` DEPOSIT_SCAN_LOOKBACK_BLOCKS=50_000; `:521` DEPOSIT_CONFIRMATION_DEPTH=32; `:517` DEPOSIT_WATCH_INTERVAL=120; `:515` MIN_DEPOSIT_USDC=50.
- `main.py:265-267` scheduler start (end of a long lifespan; a hang earlier strands all jobs).
- `domain/activation/live_checklist.py` `_gate_active_subaccount` (gate 4).
- `webtrader/backend/router.py` `admin_backfill_deposit_wallets`; `fly.toml:44` auto_stop off / min 1 machine.

Validation Tier   : MINOR (handoff documentation + state sync; no runtime code)
Claim Level       : FOUNDATION (status capture — the watcher fix itself is the next lane)
Validation Target : durable, resumable handoff of the live go-live blocker
Not in Scope      : the deposit-watcher code fix (next lane, after the error line is captured)
Suggested Next    : capture `watch_deposits DOWN err=...` → patch `integrations/polygon.py` scan path → backfill → gate 4
