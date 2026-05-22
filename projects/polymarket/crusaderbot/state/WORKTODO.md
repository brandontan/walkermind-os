# CrusaderBot — FINISHING WORKTODO

**Project:** projects/polymarket/crusaderbot
**Last Updated : 2026-05-22 22:30

> North Star: **finish CrusaderBot as a trusted, Telegram-first, multi-user, PAPER-mode autonomous trading bot.**
> No feature creep. Runtime truth > cosmetics.

---

## P0 -- Runtime Spine Validation (MANDATORY)

Prove the actual runtime spine is real end-to-end:


```text
/start
→ onboarding
↓ user state
↓ paper wallet
− default strategy
− active scanner
"钒 analysis engine
↓ risk gate
−  paper trade open
↓ position monitor
↓ paper trade close
↓ portfolio update
↓ Telegram receipt
```

Deliverables:
- [x] Runtime evidence matrix
- [x] Broken/fake/dead path map
- [x] Multi-user isolation verification
- [x] Proof PAPER ONLY posture unchanged

---

## P0 -- WebTrader Realtime Trust

Validate and fix realtime trust gaps:

- [x] Terminal updates without manual refresh
- [x] Scanner counts match backend jobs
- [x] Recent Activity synced to runtime truth
- [x] Portfolio / Wallet sync with ledger
- [x] Heartbeat / last_tick / last_scan timestamps
- [x] PAPER ONLY posture clear; LIVE not misleading

---

## P0 -- Production Integrity

Close production gaps before beta:

- [x] Apply migrations 027/029/030 — APPLIED 2026-05-21
- [x] Apply migration 031 — APPLIED 2026-05-21
- [x] Apply migration 044 (DROP access_tier) — CONFIRMED APPLIED (access_tier column gone from schema)
- [x] Fly.io deploy validation
- [x] Scheduler health / retry check
- [x] WARP-52 — portfolio_snapshots Python writer / cb_portfolio NOTIFY wiring (Issue #1245) [STANDARD] — DELIVERED WARP/portfolio-snapshots-writer 2026-05-21
- [x] Telegram notification reliability — WARP-53 DELIVERED 2026-05-21 (WARP/warp53-reliability-hardening)
- [x] Paper trading consistency (PNL, positions, ledger) — WARP-53 DELIVERED 2026-05-21 (WARP/warp53-reliability-hardening)
- [x] Logging and operational sanity

---

## P1 -- Closed Beta Hardening

Observe the runtime under real usage:

- [x] No duplicate trades — WARP-54 DELIVERED 2026-05-21 (paper.execute ON CONFLICT pinned + regression test)
- [x] No stuck positions — WARP-54 DELIVERED 2026-05-21 (stuck-position row added to /admin HUD)
- [x] No state bleed between users — WARP-54 DELIVERED 2026-05-21 (paper.close_position user_id scoping pinned + regression test, complements WARP-32)
- [x] Notification failure review — WARP-54 DELIVERED 2026-05-21 (notifications.send BadRequest → plain-text fallback)
- [x] Restart recovery validation — WARP-54 DELIVERED 2026-05-21 (scheduler startup_recovery_log job: "Resumed monitoring N open positions")
- [x] API timeout / failure behavior — WARP-54 DELIVERED 2026-05-21 (existing exit_watcher 3-tick threshold + per-position try/except confirmed correct, no code change)

---

## P1 -- Telegram UX Final (After Runtime Proven)

- [x] No dead buttons
- [x] No fake placeholder routes
- [x] State-driven keyboard
- [x] Concierge onboarding polish
- [x] Portfolio / Settings clarity
- [x] No legacy tier / operator wording

---

## P2 -- Project Finish Criteria

CRUSADERBOT is considered **DONE** only when:

- [x] WebTrader running
- [x] Runtime spine proven end-to-end
- [x] WebTrader realtime trusted
- [x] Telegram stable
- [x] Paper trading stable
- [x] No user bleed
- [x] No dead routes
- [x] Closed beta clean
- [ ] Production checklist complete

---

## Active — In Progress

- [x] WARP-61 — WebTrader confluence_scalper exposure (issue #1269) [STANDARD] — MERGED 7cbd8b814533
- [x] WARP-60 — ConfluenceScalperStrategy (issue #1267) [STANDARD] — MERGED b3ec4b7d4930
- [x] WARP-59 — Copy Wallet end-to-end bridge: copy_targets → copy_trade_tasks (Issue #1265) [STANDARD] — DELIVERED WARP/warp59-copy-wallet-e2e-bridge 2026-05-21 (MVP write path realigned to canonical execution table read by services/copy_trade/monitor.py).
- [x] WARP-58 — Fix domain/signal/copy_trade.py copy_targets schema mismatch (Issue #1263) [STANDARD] — DELIVERED WARP/warp58-copy-trade-schema-fix 2026-05-21 (closes WARP-57 SENTINEL Round-1 read-path drift).
- [x] WARP-57 — Telegram UX MVP v1 Rebuild (Issue #1260) [MAJOR] — MERGED c6ae44b18572. SENTINEL CONDITIONAL APPROVED 92/100.

---

## Deferred / NOT NOW

❌ live trading activation
❌ fancy analytics expansion
❌ dashboard redesign
❌ monetization / premium expansion
❌ new feature creep until PAPER runtime is trusted
- [x] WARP-46 — Runtime Spine Validation (Issue #1243)
- [x] WARP-62 — P0: remove threading.Lock from registry.py → eager module-level init (issue #1273) [STANDARD] — DELIVERED WARP/warp62-63-fix 2026-05-22
- [x] WARP-63 — P1: migrate CopyTradeStrategy.scan() from copy_targets → copy_trade_tasks (issue #1274) [STANDARD] — DELIVERED WARP/warp62-63-fix 2026-05-22
- [x] WARP-64 — P0: fix CI pytest failures in test_warp59_copy_wallet_bridge.py (issue #1277) [STANDARD] — DELIVERED WARP/warp64-ci-fix 2026-05-22
- [x] WARP-65 — P1: fix Telegram UX persistent keyboard + bot status + strategy label (issue #1278) [STANDARD] — DELIVERED WARP/warp65-telegram-ux-fix 2026-05-22
- [x] WARP-66 — P1: Telegram UX full polish — auto-mode keyboard routing + autotrade/copy-wallet status labels + dashboard emoji dedupe + onboarding keyboard (issue #1282) [STANDARD] — DELIVERED WARP/warp66-ux-polish 2026-05-22
- [x] SENTINEL re-audit post WARP-62+63 (issue #1276) — APPROVED 96/100 — MERGED d42b7e915356
- [x] WARP-66 — Telegram UX polish (issue #1282) [STANDARD] — MERGED ab6f397f2741
- [x] WARP-67 — P1: Telegram UX final clean — flat Markdown (no box-drawing), configured-aware Auto label, paused-aware Resume, Settings/Help double-response fix, positions title artifact (issue #1284) [STANDARD] — DELIVERED WARP/warp67-ux-final-clean 2026-05-22
- [x] WARP-67 — Telegram UX final clean (issue #1284) [STANDARD] — MERGED 2989b7c6e788
- [x] WARP-68 — Structured card format + positions pagination (issue #1286) [STANDARD] — MERGED b7355541d496
- [x] WARP-69 — Full structured card format all 66 render functions (issue #1288) [STANDARD] — MERGED b50ef1a2ce86
- [x] WARP-70 — Dynamic Auto Trade capital = balance × risk fraction (issue #1290) [MINOR] — DELIVERED WARP/warp70-dynamic-capital 2026-05-22
- [x] WARP-71 — Premium terminal UI HTML parse mode [STANDARD] — MERGED e443c212c1e7
- [x] WARP-72 — Fix phantom dot + do_start capital from _read_state [MINOR] — 93d5709c0c5c
- [x] WARP-73 — Phantom dot fix + clean Telegram HTML format [MINOR hotfix] — 5364eb97 + 7bb7a69a + c8de0a5e
