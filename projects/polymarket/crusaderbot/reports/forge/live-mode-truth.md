# live-mode-truth — single mode truth, real-balance live bankroll, switch-then-deposit

Role: WARP•R00T (owner-assigned; owner-reported 4 issues with screenshots 2026-06-11 22:42 WIB)
Branch: WARP/root-live-mode-truth
Date: 2026-06-12 02:20 Asia/Jakarta

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : paper/live mode model (writers + readers), live sizing base + risk-gate step 15, mode-scoped WebTrader money surfaces, live activation flow + auto-stop
Not in Scope      : execution router/broker paths, ledger WRITE paths (credit/debit byte-unchanged), risk constants, kill switch, strategy logic, portfolio_snapshots chart bucketing (follow-up)
Suggested Next    : WARP•R00T merge on CI green -> CD deploy (migration 096 syncs historic rows) -> owner re-checks Config/Port/Wallet surfaces

## 1. What was built

Owner reported four defects after switching to live:
(1) the switch asked for a manual capital amount; (2) live mode displayed the
PAPER balance/history relabeled "Live Mode"; (3) Config said LIVE while the
header pill said PAPER; (4) the flow demanded a deposit BEFORE switching, and
the bot did not stop on the switch.

ROOT CAUSES (verified in code + prod DB):
- TWO mode fields disagreeing: `/live/enable` wrote `trading_mode='live'` but
  never cleared `paper_mode_override` (default TRUE) — the owner's prod row
  had both `trading_mode='live'` AND `paper_mode_override=true`. Surfaces read
  different fields; `is_live_execution_allowed` (the only override consumer)
  turned out to be UNWIRED dead code, and the app-wide TopBar mode context had
  no refresh on switch (the comment claiming an SSE broadcast was aspirational).
- `wallets.balance_usdc` is one MIXED pool (paper P&L + real deposits both
  post through `ledger`, which has no mode column); every money endpoint read
  it unconditionally, and position stats never filtered `positions.mode`.
- Live sizing used the mixed balance: Kelly sizing would have sized live
  trades off the (mostly paper) $1361 wallet, bounded only by the manually
  typed cap.
- The live checklist's gate 4 required a confirmed deposit BEFORE the switch.

FIXES:
1. SINGLE MODE TRUTH — `trading_mode` is canonical. `/live/enable` now writes
   `trading_mode='live', paper_mode_override=FALSE`; `/live/disable` writes
   `'paper', TRUE`; the Telegram /paper toggle becomes safe-direction-only
   (paper ON = real drop-to-paper syncing both columns; paper OFF refuses and
   points to the typed-confirm flow — it can never silently arm live).
   Migration 096 one-shot-syncs historic rows. Frontend: new
   `TradingModeRefreshContext`; Settings refreshes the TopBar pill immediately
   on enable/disable (fixes the stale PAPER pill).
2. REAL-MONEY READ-MODEL (no schema change) — `wallet.ledger.get_live_balance`
   + `live_ledger_filter_sql`: live money = ledger rows of type
   deposit/withdraw + withdrawal-refund adjustments (ref→withdrawals) + trade
   rows whose ref joins `positions.mode='live'`. Live balance = SUM (open live
   cost already debited); paper balance = mixed − live. One bucket definition,
   pinned by test against the scan loader's copy.
3. NO MANUAL CAP — the modal's capital step is REMOVED (preview → typed
   confirm). `live_capital_cap_usdc` becomes an optional legacy tightener;
   the authoritative live bound is the REAL deposited balance: gate sizing for
   `trading_mode='live'` users uses `live_balance` as the bankroll (preloaded
   per tick by the scan loader, WARP-89 pattern), and step 15 enforces
   `open_live + size ≤ min(manual cap if >0, real balance + open_live)`, with
   `live_no_funds` when the real balance is zero. Paper sizing byte-unchanged.
4. SWITCH-THEN-DEPOSIT + AUTO-STOP — checklist gate 4 (deposit) removed
   (7 gates remain); every mode switch sets `users.auto_trade_on=FALSE`
   (existing gate step 2 enforces it), so the bot stops the instant the user
   switches and stays stopped until they deposit and re-arm. Zero real funds
   can never open a live trade (sizing collapses to 0 at step 13; step 15
   backstops the complete-set path).
5. MODE-SCOPED SURFACES — /dashboard, /wallet, /wallet/ledger,
   /portfolio/summary, /positions, /portfolio/analytics all scope by the
   user's mode: live shows real balance + live-only trades/feed; paper shows
   paper balance + paper-only history. /live/status now carries
   `live_balance_usdc`; the modal and Settings show "Live balance (deposited)"
   instead of a typed cap.

## 2. Current system architecture (relevant slice)

```
user mode truth: user_settings.trading_mode  (paper_mode_override = synced mirror)
  writers: /live/enable | /live/disable | TG /paper (drop-only)   all + auto-stop
  readers: gate _passes_live_guards, every WebTrader money endpoint, TopBar via /me

money buckets (ledger, read-model):  live = deposit|withdraw|refund-adj|live-trade rows
  live balance  -> live bankroll (gate sizing) + step-15 ceiling + live-mode display
  mixed - live  -> paper display balance (paper sizing stays on mixed wallet)

scan loader preloads live_balance_usdc per user/tick -> TradeSignal -> GateContext
  (no per-candidate DB read; one-shot fallback for legacy call sites)
```

## 3. Files created / modified

- projects/polymarket/crusaderbot/wallet/ledger.py — get_live_balance + live_ledger_filter_sql (read-model)
- projects/polymarket/crusaderbot/domain/risk/gate.py — live sizing base; step 15 rework (live_no_funds / manual-cap-tightens); resume_safety_check step 15 same semantics; GateContext.live_balance_usdc
- projects/polymarket/crusaderbot/domain/activation/live_checklist.py — deposit gate removed (7 gates)
- projects/polymarket/crusaderbot/webtrader/backend/router.py — enable/disable mode-sync + auto-stop + optional cap; /live/status live_balance; mode-scoped dashboard/wallet/ledger/portfolio/positions/analytics
- projects/polymarket/crusaderbot/webtrader/backend/schemas.py — LiveStatus/LiveEnableRequest/LiveEnableResponse
- projects/polymarket/crusaderbot/services/trade_engine/engine.py — TradeSignal.live_balance_usdc (+getattr stub compat)
- projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py — loader preloads live_balance_usdc (bucket SQL mirror)
- projects/polymarket/crusaderbot/bot/handlers/strategy.py — /paper toggle safe-direction + sync + auto-stop
- projects/polymarket/crusaderbot/migrations/096_mode_truth_sync.sql — historic row sync (idempotent)
- projects/polymarket/crusaderbot/webtrader/frontend/src/App.tsx — TradingModeRefreshContext
- projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts — enableLive(phrase); LiveStatus/LiveEnableResponse types
- projects/polymarket/crusaderbot/webtrader/frontend/src/components/LiveActivationModal.tsx — cap step removed; deposit gate label removed; auto-stop messaging
- projects/polymarket/crusaderbot/webtrader/frontend/src/pages/SettingsPage.tsx — live balance row; copy; pill refresh on switch
- tests: test_live_mode_truth.py (new, 11 tests); test_live_checklist / test_live_activation_flow / test_resume_safety_check / test_telegram_live_truth updated to the new contracts; test_admin_console / test_webtrader_positions / test_fallback harnesses extended for the new reads
- projects/polymarket/crusaderbot/reports/forge/live-mode-truth.md + state files

## 4. What is working

- FULL SUITE 3459 passed / 11 skipped (+11 on 3448); ruff clean; frontend tsc + vite build clean.
- New tests prove: live sizes off $40 real (final = 40×0.06×0.20) while $10k mixed is ignored; paper sizing byte-identical; $0 funds → reject; manual cap only tightens (step 15); bucket SQL pinned identical in ledger + loader; both writers sync both columns + auto-stop; Telegram toggle can never write trading_mode='live'; deposit gate pinned ABSENT; LiveEnableRequest validates without a cap.

## 5. Known issues

- /portfolio/chart (equity sparkline) still draws from portfolio_snapshots, which are not mode-bucketed — the curve mixes paper history. Display-only; follow-up lane.
- Steps 5/6/8 (daily-loss, drawdown, deployment%) still compute off the mixed pool — conservative for live users (paper losses can halt live trading, never the reverse-unsafe direction). Documented follow-up if per-mode circuit breakers are wanted.
- The owner's current live row has `live_capital_cap_usdc=100` from the old flow — now acts only as a manual tightener; clear it to 0 in Settings re-enable if undesired.

## 6. What is next

1. Merge on CI green (WARP•R00T full-bypass) -> CD deploy; migration 096 syncs the owner's row (override TRUE→FALSE under trading_mode='live').
2. Owner re-test: header pill LIVE everywhere; Wallet/Port show ~$1.00 live balance + only the deposit credit in activity; switch to paper → paper history returns; switching either way stops Auto-Trade.
3. Deposit real USDC.e → live balance grows → sizing scales with it. No amount to type anywhere.
