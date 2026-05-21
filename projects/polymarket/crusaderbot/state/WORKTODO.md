# CrusaderBot — FINISHING WORKTODO

**Project:** projects/polymarket/crusaderbot
**Last Updated : 2026-05-21 06:06

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

- [ ] No duplicate trades
- [ ] No stuck positions
- [ ] No state bleed between users
- [ ] Notification failure review
- [ ] Restart recovery validation
- [ ] API timeout / failure behavior

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
- [ ] Runtime spine proven end-to-end
- [ ] WebTrader realtime trusted
- [ ] Telegram stable
- [ ] Paper trading stable
- [ ] No user bleed
- [ ] No dead routes
- [ ] Closed beta clean
- [ ] Production checklist complete

---

## Deferred / NOT NOW

❌ live trading activation
❌ fancy analytics expansion
❌ dashboard redesign
❌ monetization / premium expansion
❌ new feature creep until PAPER runtime is trusted
- [x] WARP-46 — Runtime Spine Validation (Issue #1243)
