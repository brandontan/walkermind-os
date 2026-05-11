# WARP•SENTINEL Report — crusaderbot-fast-trade-engine

**Branch validated:** WARP/crusaderbot-fast-trade-engine

**Source PR:** #942

**Source report:** projects/polymarket/crusaderbot/reports/forge/crusaderbot-fast-trade-engine.md

**Validation date:** 2026-05-11 14:30 Asia/Jakarta

**Validation Tier:** MAJOR

**Claim Level:** FULL RUNTIME INTEGRATION

**Sentinel branch:** WARP/sentinel-crusaderbot-fast-trade-engine

**Sentinel PR target:** WARP/crusaderbot-fast-trade-engine (FORGE PR still open)

---

## 1. Environment

- Environment: dev (paper trading only — `ENABLE_LIVE_TRADING` NOT SET; activation guards OFF)
- Risk: ENFORCED
- Infra: warn-only (dev)
- Telegram: warn-only (dev)
- Paper-only posture preserved end-to-end. No live execution path is reachable.

---

## 2. Validation Context

- Validation target (from issue #943): active paper signal-to-position runtime path plus TP/SL worker contract.
- Audit scope per issue:
  - Normal active scan path routes through `TradeEngine` (no direct `router_execute`).
  - `TradeEngine.execute()` always evaluates the 13-step risk gate before router execution.
  - Approved path creates paper order/position, returns correct `final_size_usdc` / `chosen_mode`.
  - Rejected path performs no `execution_queue` insert / mark-executed.
  - Duplicate / idempotency-replay path is safe and queue-insert-skipped.
  - Crash-recovery direct router path remains narrow and clearly documented.
  - TP/SL exit watcher behavior remains unchanged.
  - Activation guards untouched; live trading remains disabled.
  - Tests cover the scan-path → TradeEngine integration.
  - Forge report + state files reflect code truth.
- Not in scope: live trading, real CLOB execution, Copy Trade execution, trade notifications, UI changes, activation guard flips.

---

## 3. Phase 0 Pre-Test Checks

- [PASS] PR #942 exists and is open (`state="open"`, `mergeable_state="clean"`, head SHA `0b6c0f8`).
- [PASS] Branch matches `WARP/crusaderbot-fast-trade-engine` exactly (case-sensitive, no underscores/dots/dates).
- [PASS] Forge report at correct path: `projects/polymarket/crusaderbot/reports/forge/crusaderbot-fast-trade-engine.md` (no phase prefix, no date suffix).
- [PASS] Forge report contains all 6 mandatory sections + Tier/Claim Level/Validation Target/Not in Scope/Suggested Next Step metadata.
- [PASS] `projects/polymarket/crusaderbot/state/PROJECT_STATE.md:1` carries full timestamp `2026-05-11 10:00` (Asia/Jakarta) — date-only failure rule satisfied.
- [PASS] No `phase*/` folders present in the repo (`find projects/polymarket/crusaderbot -type d -name "phase*"` returns nothing).
- [PASS] Hard delete policy: no shim/re-export files; `_build_gate_context` removed from scan job and now lives only inside `TradeEngine._build_gate_context` (`services/trade_engine/engine.py:191`).
- [PASS] Implementation evidence for critical layers: `services/trade_engine/engine.py` (212 LOC), `services/trade_engine/__init__.py` (10 LOC), `services/signal_scan/signal_scan_job.py` (543 LOC).
- [PASS] No hardcoded secrets / API keys in PR diff.
- [PASS] Kelly cap = 0.25 (`projects/polymarket/crusaderbot/domain/risk/constants.py:4` → `KELLY_FRACTION = 0.25`); gate clamps per-profile kelly to this cap (`domain/risk/gate.py:269`).
- [PASS] No silent failure handling (`except: pass` / `except Exception: pass`) in `services/trade_engine/` or `services/signal_scan/`. Every `except` block in `signal_scan_job.py` logs via `log.warning` / `log.error`.
- [PASS] `import threading` is absent from the PR scope; asyncio only.
- [PASS] No activation guard mutations: PR diff contains no changes to `config.py`, `.env*`, or `fly.toml`.
- [PASS] `python -m py_compile` clean on all three modified/new modules.
- [PASS] Claim-targeted suite green: `pytest tests/test_fast_track_a.py` → 47 passed in 1.32s; `pytest tests/test_signal_scan_job.py` → 26 passed in 0.56s.

Phase 0 verdict: PASS. Proceed to phased validation.

---

## 4. Findings

### Phase 1 — Functional

- `services/trade_engine/engine.py:62-100` defines `TradeSignal` (frozen dataclass) and `TradeResult` (frozen dataclass) as typed contracts; both `@dataclass(frozen=True)` — mutation raises (verified by `test_frozen_raises_on_mutation` at `tests/test_fast_track_a.py:612`).
- `TradeEngine.execute()` at `services/trade_engine/engine.py:110-187` runs:
  1. `_build_gate_context(signal)` (line 119) → `GateContext`.
  2. `_risk_evaluate(gate_ctx)` (line 121) → `GateResult`.
  3. On rejection (line 123): returns `TradeResult(approved=False, mode=None, order_id=None, position_id=None, ...)` with `rejection_reason` + `failed_gate_step` populated. `_router_execute` is NOT called — covered by `TestTradeEngineGateRejected` (7 cases at `tests/test_fast_track_a.py:167-268`).
  4. On approval (line 142): `_router_execute(...)` is invoked with `final_size = gate_result.final_size_usdc or signal.proposed_size_usdc` (line 140). `tp_pct`/`sl_pct` forwarded from `TradeSignal` (lines 157-158).
- `chosen_mode` set from router’s actual `mode` field, not gate decision (`engine.py:176`). Verified by `test_paper_chosen_mode_when_guards_off` at `tests/test_fast_track_a.py:397`.
- `final_size_usdc` propagated through `TradeResult` for downstream queue persistence (`engine.py:186`). Verified by `test_final_size_from_gate_used` at `tests/test_fast_track_a.py:308`.

### Phase 2 — Pipeline (no bypass)

- Active scan loop: `services/signal_scan/signal_scan_job.py:494-540` (`run_once`) iterates enrolled users → loads `SignalCandidate`s → calls `_process_candidate(row, cand)`.
- `_process_candidate` at `signal_scan_job.py:320-487` executes in this fixed order:
  1. Crash-recovery resume (lines 348-407): only fires when `_load_stale_queued_row` returns a row with `status='queued'`. Calls `router_execute` directly (line 375) AFTER `kill_switch_is_active()` check (line 355). Returns immediately (line 407) — does NOT fall through to normal path.
  2. Permanent dedup (lines 410-418): `_publication_already_queued` checks `status IN ('executed','failed')`.
  3. Market lookup (lines 421-424).
  4. TradeSignal build (lines 426-434) via `_build_trade_signal`.
  5. `_engine.execute(signal)` (line 439) — the ONLY normal execution path.
  6. Rejection short-circuit (lines 445-452) returns before any queue mutation.
  7. Queue insert + mark executed (lines 454-486).
- `router_execute` symbol still imported (`signal_scan_job.py:47`) but used only inside the crash-recovery branch. Grep confirms only one direct `router_execute(...)` call in the module (line 375). No pipeline bypass for new signals.
- Module-level singleton `_engine: TradeEngine = TradeEngine()` at `signal_scan_job.py:62` — stateless; safe across ticks.

### Phase 3 — Failure modes

- TradeEngine exception propagation: `engine.py:35-37` (docstring) + actual behavior verified by `test_router_raises_propagates` (`tests/test_fast_track_a.py:373`) and `test_gate_raises_propagates` (line 387).
- Scan-loop catches TradeEngine exceptions per-candidate at `signal_scan_job.py:438-443` → logs `scan_outcome=failed` → returns; does not crash tick or queue insert.
- Crash recovery failures logged and marked failed at `signal_scan_job.py:400-406` (router raises → `_mark_failed`; `_mark_failed` failure itself is also caught at line 405-406, downgraded to warning).
- Queue insert failure path: `signal_scan_job.py:471-473` catches and warns; `_mark_executed` failure path: `signal_scan_job.py:476-478` catches and warns. No silent swallowing.
- Idempotent duplicate (router returns `status="duplicate"`): mapped to `TradeResult(mode="duplicate")` at `engine.py:165-166`. Scan job skips queue insert when `result.mode == "duplicate"` (`signal_scan_job.py:458`). Verified by `test_process_candidate_duplicate_mode_skips_queue_insert` at `tests/test_fast_track_a.py:850`.
- Kill switch during crash-recovery: `signal_scan_job.py:355-357` aborts resume; row stays `'queued'` for the next tick. Verified by `test_process_candidate_skips_resume_when_kill_switch_active` (`tests/test_signal_scan_job.py:628`).
- Concurrent-tick on the same `(user, publication_id)`: gate step 10 records the idempotency key (`domain/risk/gate.py:235-241,299`) and paper engine de-duplicates on the same key. Both lines of defense are exercised by the engine duplicate test (`tests/test_fast_track_a.py:291`).

### Phase 4 — Async safety

- All entry points are `async def`; no thread spawning anywhere in scope (`grep -rn "threading\." services/trade_engine services/signal_scan` returns no hits in the new code; the only match is the docstring line at `engine.py:33` stating "asyncio only — no threading").
- `_engine` singleton is stateless — all per-call state is local to `execute()`; no instance attributes mutated. Safe across concurrent `asyncio` ticks.
- DB pool acquired per call (`signal_scan_job._load_*`, `gate._idempotent_already_seen`, etc.); no shared cursors.
- `_record_idempotency` (gate step 10, `domain/risk/gate.py:112-120`) uses `INSERT ... ON CONFLICT (key) DO NOTHING` — race-safe.
- `_insert_execution_queue` (`signal_scan_job.py:153-182`) uses `INSERT ... ON CONFLICT (user_id, publication_id) ... DO NOTHING RETURNING id` — race-safe; returns `False` when the row already existed.

### Phase 5 — Risk rules (in-code)

- Kelly = 0.25: `domain/risk/constants.py:4` (`KELLY_FRACTION = 0.25`); per-profile values clamped down at `domain/risk/gate.py:269` (`kelly = min(float(profile.get("kelly", K.KELLY_FRACTION)), K.KELLY_FRACTION)`); assertion at line 267-268 hard-fails if `KELLY_FRACTION` drifts above 0.5.
- Position cap: gate step 13 enforces `max_pos_size = balance * max_pos_pct * kelly` (`domain/risk/gate.py:273`); `assert 0 < max_pos_pct < 1.0` (`gate.py:271-272`).
- Daily loss cap: gate step 5 (`gate.py:188-194`).
- Drawdown halt: gate step 6 (`gate.py:197-205`) plus live-to-paper fallback trigger when crossed in live mode.
- Liquidity floor: gate step 11 (`gate.py:243-249`).
- Dedup + idempotency: gate step 10 (`gate.py:234-241`).
- Kill switch: gate step 1 (`gate.py:152-163`) + scan job crash-recovery short-circuit (`signal_scan_job.py:355-357`).
- All thirteen gate steps run before any `_router_execute` invocation on the normal path (engine.py:121 evaluates BEFORE engine.py:142 calls the router).
- The crash-recovery direct `router_execute` (signal_scan_job.py:375) does NOT bypass risk for new signals — the row it resumes was already gate-approved on a prior tick (per the documented contract at `signal_scan_job.py:20-27`), and a fresh kill-switch check still runs before the resume.

### Phase 6 — Latency

- No latency claim made by FORGE; not validated end-to-end here. The added indirection (`scan → _engine.execute → gate → router`) is one extra Python frame versus the previous direct call and adds no I/O. Test suite executes 47 hermetic tests in 1.32 s, indicating the new wrapper adds negligible overhead.

### Phase 7 — Infra

- No infra layer changes (Redis/PostgreSQL/Telegram surfaces untouched in PR diff). Risk logger continues to use `domain/risk/gate._log` (`gate.py:50-61`).

### Phase 8 — Telegram

- No Telegram surfaces touched in this PR. TP/SL exit watcher (`domain/execution/exit_watcher.py`) untouched (diff against merge-base shows zero changes to this file). Existing TP_HIT / SL_HIT / FORCE_CLOSE / MANUAL contract preserved and re-tested by 10 watcher tests (`tests/test_fast_track_a.py:486-608`).

---

## 5. Score Breakdown

- Architecture: 19/20 — clean dataclass contract, isolated TradeEngine module, single-source-of-truth gate evaluation. -1 for the in-flight `'queued'` row being addressable by the crash-recovery loader (documented + idempotency-safe but semantically unusual).
- Functional: 20/20 — every claimed path verified via code + tests.
- Failure modes: 19/20 — exception paths, kill-switch interaction, idempotent-duplicate skip, and concurrent-tick race all covered. -1 because `_load_stale_queued_row` has no age discriminator (any `'queued'` row qualifies); behavior is still safe but the safety margin relies on the paper engine’s idempotency.
- Risk: 20/20 — Kelly 0.25 hard-capped, gate-first invariant preserved, no guard mutations.
- Infra+TG: 9/10 — exit watcher and Telegram untouched; risk_log persistence relies on the DB layer with logged-not-silenced failure handling.
- Latency: 9/10 — no real I/O added by the indirection; no end-to-end timing harness in scope.

**Total: 96 / 100.**

---

## 6. Critical Issues

None found.

No P0 issues.

---

## 7. Status

- Verdict: APPROVED.
- Score: 96 / 100.
- Critical (P0) issue count: 0.
- All Phase 0 checks PASS.
- Claim-targeted test suite green (47 + 26 hermetic tests).
- No live execution path reachable; activation guards remain OFF.

---

## 8. PR Gate Result

- Source PR #942 may be merged at WARP🔹CMD discretion.
- Sentinel PR target: `WARP/crusaderbot-fast-trade-engine` (FORGE PR open — SENTINEL PR targets source branch per AGENTS.md / CLAUDE.md branching rule).
- No direct-to-main bypass.

---

## 9. Broader Audit Finding

- TradeEngine wrapper is correctly slotted between scan loop and router; risk gate remains the only path to `router_execute` on the normal lane.
- Crash-recovery direct router call is the only documented exception and is narrow + kill-switch-guarded.
- Code matches FORGE report claim ("FULL RUNTIME INTEGRATION"): the active scan runtime, not just a unit-test harness, routes through TradeEngine.

---

## 10. Reasoning

The claim is "TradeEngine wired into active signal scan runtime; normal path = signal → TradeEngine → 13-step gate → router → paper fill; crash-recovery path narrow." Each leg of this claim is verified by both code reading and a passing hermetic test:

- `signal_scan_job._process_candidate` invokes `_engine.execute(signal)` for new signals (line 439); no other `router_execute` call exists outside the crash-recovery block.
- `TradeEngine.execute` evaluates the gate at `engine.py:121` BEFORE the router call at `engine.py:142`. Rejection short-circuits without touching the router.
- `TradeResult` carries `final_size_usdc` from the gate and `chosen_mode` from the router’s actual response, preventing live/paper drift if guards flip mid-flight.
- Idempotent duplicate is surfaced as `mode="duplicate"` and the scan job skips the queue insert in that case.
- Crash-recovery is the only direct `router_execute` call and is shielded by both `_load_stale_queued_row` (only matches `status='queued'`) and a fresh `kill_switch_is_active()` check.
- Activation guards (`ENABLE_LIVE_TRADING`, `EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`, `USE_REAL_CLOB`) are not mutated; PR diff contains no config / fly.toml / .env changes.
- Forge report (`reports/forge/crusaderbot-fast-trade-engine.md`) and PROJECT_STATE.md (`Last Updated : 2026-05-11 10:00`) match code truth.

No critical issues found. Score = 96 / 100. Verdict = APPROVED.

---

## 11. Fix Recommendations

None required for merge. Optional post-merge polish (P2 — does not block):

- Add an age discriminator (e.g. `inserted_at < NOW() - INTERVAL '2 minutes'`) to `_load_stale_queued_row` so the crash-recovery loader matches only genuinely stale rows, not in-flight rows from a concurrent tick. Idempotency already makes this safe, but a stricter discriminator would remove the unusual semantics flagged in the score breakdown.

---

## 12. Out-of-scope Advisory

- Track B (Copy Trade execution), Track C (notifications), Track D (risk caps + kill-switch hardening), and Track E (daily P&L report) remain blocked behind Track A merge — not part of this audit.
- Live trading activation, real CLOB execution, multi-user isolation audit, and admin/onboarding polish all remain out of scope.

---

## 13. Deferred Minor Backlog

- [P2] `_load_stale_queued_row` age discriminator — see §11.

(All other `[DEFERRED]` items already in `PROJECT_STATE.md [KNOWN ISSUES]` remain valid and untouched by this PR.)

---

## 14. Telegram Visual Preview

No Telegram surfaces changed in this PR. The existing exit-notification surface (TP_HIT / SL_HIT / FORCE_CLOSE / MANUAL) continues to operate from `domain/execution/exit_watcher.py`. Sample alert preview unchanged:

```
[CrusaderBot] Position closed
Market : Will X happen?
Side   : YES
Size   : 25.00 USDC
Exit   : 0.72 (TP_HIT)
P&L    : +5.00 USDC
Mode   : paper
```

Dashboard / 7-alert event set was not part of this PR scope and was not re-validated here.

---

**End of report.**
