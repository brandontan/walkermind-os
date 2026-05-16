# WARP•FORGE Report — trading-unblock

**Branch**: claude/unblock-trading-positions-l13YL
**Date**: 2026-05-16
**Validation Tier**: MAJOR
**Claim Level**: NARROW INTEGRATION

---

## 1. What Was Built

Four fixes to unblock CrusaderBot trading, which was at 0 trades due to 5 positions
from May 13 permanently occupying all 5 concurrent-trade gate slots:

**Task 1 — exit_watcher: two-phase MARKET_EXPIRED sweep**
- Phase A: `run_once()` retries `_fetch_live_price()` once on None; if still None →
  `_close_expired_position()` → atomic close (no CLOB order)
- Phase B: new `list_open_on_resolved_markets()` query catches positions on markets where
  `m.resolved = TRUE` (completely invisible to Phase A's `WHERE m.resolved = FALSE` filter)
- `close_as_expired()`: atomic 3-statement transaction: UPDATE positions (status='closed',
  exit_reason='market_expired', pnl_usdc=0.0, closed_at=NOW()) + UPDATE wallets
  (balance_usdc += size_usdc) + INSERT ledger (type='trade_close')
- `alert_user_market_expired()`: Telegram notification with refunded amount
- `RunResult` dataclass: submitted/expired/held/errors counts replace bare `int` return

**Task 2 — gate.py: verified correct, no change**
Gate step 7 queries `COUNT(*) FROM positions WHERE status='open'`. Returns 0 after Task 1.
Will unblock automatically.

**Task 3 — scheduler: immediate signal scan on startup**
- `next_run_time=datetime.now(timezone.utc)` on signal_scan, signal_following_scan,
  market_signal_scanner — fires immediately on deploy, not after 3-min interval
- `check_exits()` returns `dict` (RunResult as JSON-serializable dict)

**Task 4 — monitoring: metadata in job_runs**
- Migration 030: `ALTER TABLE job_runs ADD COLUMN IF NOT EXISTS metadata JSONB`
- `job_tracker.record_job_event()`: accepts `metadata: Optional[dict]` → writes to JSONB column
- Scheduler listener: captures `event.retval` as metadata for all jobs returning dict

---

## 2. Current System Architecture

```
EXIT_WATCHER (60s tick)
  Phase A: list_open_for_exit() [m.resolved=FALSE]
    → _fetch_live_price() → retry once on None → MARKET_EXPIRED close
    → evaluate() TP/SL/force/strategy → _act_on_decision()
  Phase B: list_open_on_resolved_markets() [m.resolved=TRUE]
    → _close_expired_position() directly

MARKET_EXPIRED close path (atomic tx):
  positions: status='closed', exit_reason='market_expired', pnl_usdc=0, closed_at=NOW()
  wallets:   balance_usdc += size_usdc
  ledger:    INSERT type='trade_close'
  Telegram:  alert_user_market_expired()

GATE (step 7): COUNT(*) WHERE status='open' < max_concurrent=5 → PASS

SIGNAL SCAN: fires immediately on startup (next_run_time=now)

JOB MONITORING: job_runs.metadata JSONB per tick (submitted/expired/held/errors)
```

---

## 3. Files Created / Modified

| Action | Path |
|--------|------|
| Modified | `projects/polymarket/crusaderbot/domain/positions/registry.py` |
| Modified | `projects/polymarket/crusaderbot/domain/execution/exit_watcher.py` |
| Modified | `projects/polymarket/crusaderbot/monitoring/alerts.py` |
| Modified | `projects/polymarket/crusaderbot/scheduler.py` |
| Modified | `projects/polymarket/crusaderbot/tests/test_exit_watcher.py` |
| Modified | `projects/polymarket/crusaderbot/domain/ops/job_tracker.py` |
| Created  | `projects/polymarket/crusaderbot/migrations/030_job_runs_metadata.sql` |

---

## 4. What Is Working

- `ExitReason.MARKET_EXPIRED = "market_expired"` added to enum + WATCHER_EXIT_REASONS
- `list_open_on_resolved_markets()` surfaces Phase B positions
- `close_as_expired()` is atomic and idempotent (WHERE status='open' guard)
- `_close_expired_position()` handles both Phase A (None price) and Phase B (resolved market)
- Two-attempt retry before declaring expired (existing tenacity handles network errors internally)
- `alert_user_market_expired()` sends refund confirmation to user
- `check_exits()` returns RunResult dict for APScheduler retval capture
- `next_run_time=datetime.now(timezone.utc)` triggers signal scan at startup
- Migration 030 adds JSONB metadata column idempotently
- `job_tracker.record_job_event()` writes metadata for any job returning dict
- Scheduler listener captures `event.retval` for all success-path job executions
- Tests: `_patch_registry()` updated to return actual position prices (prevents
  spurious expired-close in existing TP/SL tests); two new MARKET_EXPIRED tests added

---

## 5. Known Issues

- **Cross-pipeline race with redemption pipeline**: if `redeem_router.detect_resolutions()`
  processes a resolved-market position first (sets status='redeemed'), `close_as_expired()`
  finds `status != 'open'` and returns False (idempotent, safe). Monitor operator logs post-deploy.
- **Migration must be applied before deploy**: migration 030 must run before the scheduler
  starts writing metadata, else `record_job_event()` will fail on the metadata column insert.
  Apply via standard migration runner before deploying.
- **job_runs metadata column backfill**: rows before this deploy will have `metadata = NULL`.
  This is expected — no backfill needed.

---

## 6. What Is Next

```
WARP•SENTINEL validation required for trading-unblock before merge.
Source: projects/polymarket/crusaderbot/reports/forge/trading-unblock.md
Tier: MAJOR
```

Post-merge acceptance check:
1. `SELECT status, exit_reason FROM positions WHERE exit_reason='market_expired'` → 5 rows
2. `SELECT balance_usdc FROM wallets WHERE user_id = <walk3r69>` → ~$1000
3. `SELECT metadata FROM job_runs WHERE job_name='exit_watch' ORDER BY started_at DESC LIMIT 1` → JSON with counts
4. Telegram notification received for each expired position
5. Signal scan job_runs row with started_at ≈ deploy time (immediate startup scan)
6. New orders in DB within 5 min of deploy

---

**Validation Tier**: MAJOR
**Claim Level**: NARROW INTEGRATION
**Validation Target**: exit_watcher expired-market close path + gate unblock + signal scan startup + job_runs metadata
**Not in Scope**: CLOB execution path, redemption pipeline, live trading mode, WebTrader
**Suggested Next Step**: Apply migration 030 to production, deploy, run WARP•SENTINEL validation
