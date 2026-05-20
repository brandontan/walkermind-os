# CrusaderBot — FINISHING WORKTODO

**Project:** projects/polymarket/crusaderbot
**Last Updated:** 2026-05-20 Asia/Jakarta

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
- [ ] Runtime evidence matrix
- [ ] Broken/fake/dead path map
- [x] Multi-user isolation verification
- [ ] Proof PAPER ONLY posture unchanged

---

## P0 -- WebTrader Realtime Trust

Validate and fix realtime trust gaps:

- [ ] Terminal updates without manual refresh
- [ ] Scanner counts match backend jobs
- [ ] Recent Activity synced to runtime truth
- [ ] Portfolio / Wallet sync with ledger
- [ ] Heartbeat / last_tick / last_scan timestamps
- [ ] PAPER ONLY posture clear; LIVE not misleading

---

## P0 -- Production Integrity

Close production gaps before beta:

- [ ] Apply pending migrations (027/029/030/031 as required)
- [ ] Fly.io deploy validation
- [ ] Scheduler health / retry check
- [ ] Telegram notification reliability
- [ ] Paper trading consistency (PNL, positions, ledger)
- [ ] Logging and operational sanity

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

- [ ] No dead buttons
- [ ] No fake placeholder routes
- [x] State-driven keyboard
- [x] Concierge onboarding polish
- [ ] Portfolio / Settings clarity
- [ ] No legacy tier / operator wording

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
