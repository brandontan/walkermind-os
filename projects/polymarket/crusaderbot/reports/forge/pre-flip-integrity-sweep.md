# pre-flip-integrity-sweep

**Role:** WARP•R00T
**Tier:** MINOR (read-only audit; state sync + report only)
**Claim Level:** FOUNDATION
**Validation Target:** post-merge integrity of the 10 Polybot lanes (#1481 → #1493) + pre-flip safety review of the 4 flag-gated knobs queued for operator enablement
**Not in Scope:** code modifications; live-mode hardening (recorded as follow-up backlog)

---

## 1. What was built

Read-only audit. Two deliverables:

1. **Post-merge integrity sweep** — cross-lane interaction audit covering the 10 Polybot lanes merged this session: Alert Center typed cards (#1481), Admin Drawer (#1484), Lane A complete-set-edge-gate (#1485), Lane B bankroll-circuit-breaker (#1486), Lane C bnb-monitor-only (#1487), Lane D-1 inventory-tracker-foundation (#1488), Lane D-2 safe-close-imbalance-override (#1490), Lane D-3 flip-hunter-fast-topup (#1491), Lane D-4 close-sweep-dual-leg (#1492), Hotfix preset-activation (#1493).
2. **Pre-flip safety review** — adversarial code-level review of the four flag-gated knobs queued for operator enablement once paper stats validate:
   - `BANKROLL_CIRCUIT_BREAKER_ENABLED`
   - `SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED`
   - `FLIP_HUNTER_FAST_TOPUP_ENABLED`
   - `CLOSE_SWEEP_DUAL_LEG_ENABLED`

No production code touched. Two findings surfaced (M-1, M-2) for backlog hardening — both safe to defer in PAPER, both recommended-fix before any of the flag-gated lanes flips to LIVE.

---

## 2. Current system architecture

### Gate ordering inside `_process_candidate` (post-merge)

```
step 0   crash-recovery (in-flight trade completion)
step 0a  BANKROLL_CIRCUIT_BREAKER (config-gated; fails open on config-read failure)
step 1   permanent dedup (execution_queue)
step 1a-2 SAFE_CLOSE_IMBALANCE_OVERRIDE (config-gated; fails closed on config-read failure)
step 1b  open-position dedup (override-aware: side-aware when override active)
step 1c  signal freshness gate
step 2   market lookup
step 2b  target-price drift guard
step 3   strategy params resolution
step 3a  TOB freshness gate
step 3b-0a COMPLETE_SET_EDGE gate (Lane A)
step 3b-i candle sub-cent tick guard
step 3c  fill-time price band
step 4-5 risk gate + execution_queue insert + paper engine
post-execute: safe_close direction-limit record (Lane 4)
post-execute: FLIP_HUNTER_FAST_TOPUP / CLOSE_SWEEP_DUAL_LEG (config-gated)
```

### Flag-gated lane wiring

```text
config.py                            signal_scan_job.py
─────────────────                    ─────────────────────────────────────
BANKROLL_CIRCUIT_BREAKER_ENABLED  →  step 0a _evaluate_bankroll_circuit_breaker
                                     reads _bankroll_ema_baseline (Lane 5)
                                     latched: trip @ baseline*0.20 / resume @ *0.22

SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED →  step 1a-2
                                          compute_market_inventory()
                                          dataclasses.replace(side=lagging)
                                          step 1b switches to _has_open_position_for_side

FLIP_HUNTER_FAST_TOPUP_ENABLED      ─┐  post-execute _maybe_fire_fast_topup
CLOSE_SWEEP_DUAL_LEG_ENABLED        ─┤    via _resolve_eligible_topup_presets(cfg)
                                     │    D-3 set {safe_close, flip_hunter}
                                     │    D-4 set {close_sweep}
                                     │    union by flag; empty → bail
                                     └─  shared FAST_TOPUP_MIN_USDC + COOLDOWN_SECONDS
```

---

## 3. Files created / modified

```text
projects/polymarket/crusaderbot/reports/forge/pre-flip-integrity-sweep.md   (NEW)
projects/polymarket/crusaderbot/state/PROJECT_STATE.md                       (sections updated)
projects/polymarket/crusaderbot/state/CHANGELOG.md                            (one-line append)
```

Zero production code modified. M-1 and M-2 findings deferred to a future hardening lane (see §6).

---

## 4. What is working — Integrity sweep results

| Interaction | Verdict | Evidence |
|---|---|---|
| State files in sync | CLEAN | All 10 lanes accounted for in `PROJECT_STATE.md [COMPLETED]` and `CHANGELOG.md` |
| D-2 → D-3 → D-4 chain | CLEAN | D-2 flips lead side; D-3/D-4 target the resulting lagging leg; cooldown gates `_fast_topup_last_at` |
| `_resolve_eligible_topup_presets` flag matrix | CLEAN | `signal_scan_job.py:760-783` — `getattr(..., False)` handles partial cfg; union semantics correct |
| Bankroll CB ↔ Lane 5 baseline | CLEAN | `_ensure_bankroll_baseline_seeded` (`signal_scan_job.py:300-322`) seeds baseline independently; no-op when Lane 5 already seeded |
| complete-set-edge-gate + D-2 ordering | CLEAN | Gate at step 3b-0a (`signal_scan_job.py:1905+`) runs AFTER D-2 (step 1a-2) — evaluates the flipped candidate's metadata stamp correctly |
| bnb-monitor-only + preset-activation hotfix | CLEAN | Hotfix #1493 (`webtrader/backend/router.py:_sanitize_selected_assets`) heals the squash-merge gap from #1487 retroactively for legacy persisted assets |
| Direction-limit + fast-topup interaction | CLEAN | `_safe_close_record_entry` (`signal_scan_job.py:2193-2196`) records the lead side; top-up targets opposite side — no double-count |
| CB gate ordering (vs crash recovery) | CLEAN | Step 0 (crash recovery) runs BEFORE step 0a (CB) — in-flight trade completion never blocked |
| Phase folder / shim audit | CLEAN | Zero `phase*/` folders, zero shims, zero compatibility re-exports |
| Telemetry coverage | CLEAN | All four flag-gated lanes emit structured `scan_outcome` log events on success + rejection paths |
| Config-read failure posture | CLEAN | CB fails OPEN (won't lock users out); imbalance override fails CLOSED (won't relax dedup); fast-topup fails CLOSED (skipped) |

### Per-lane safety review

#### BANKROLL_CIRCUIT_BREAKER_ENABLED — SAFE TO ENABLE FIRST

| Check | Result |
|---|---|
| Config-read failure | Fails OPEN (breaker disabled). Correct — broken config never silently locks users out |
| First-observation baseline | `_ensure_bankroll_baseline_seeded` (line 300) seeds on first balance read independently from Lane 5 |
| Default threshold (0.20) | Trips at 80% drawdown — conservative for paper. PAPER starting balance $100 needs to fall to $20 to trip |
| Hysteresis (0.10) | Resume requires balance > baseline × 0.22 — prevents oscillation at boundary |
| Lane 5 baseline reuse | Both CB and Lane 5 read from `_bankroll_ema_baseline` — same denominator, consistent reporting |
| Crash-recovery ordering | Step 0 (crash recovery) precedes step 0a (CB). In-flight trades complete; only NEW entries blocked |

**Verdict:** safe to flip first. Watch `skipped_circuit_breaker` log event rate for 24h. Expected: near-zero on healthy accounts.

#### SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED — SAFE TO ENABLE THIRD

| Check | Result |
|---|---|
| Config-read failure | Fails CLOSED (override disabled). Correct — won't silently relax dedup |
| Scope guard | Only fires for `late_entry_v3` candidates with `active_preset == 'safe_close'` |
| Side-aware dedup | Drops 24h closed-position window — intentional; override is for a NEW opposite-side position |
| Always-on when `|imbalance| > threshold` | Activates side-aware dedup even when candidate naturally targets lagging — prevents broad dedup from blocking correctly-directed rebalance |
| Direction-limit interaction | Override mutates `cand.side` before `_safe_close_record_entry` — limit records the final (flipped) side |

**Note on closed-window removal:** After a safe_close position closes, D-2 can immediately reopen on the same market on the lagging side. `SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR=8` is the only frequency backstop for the same side; the opposite side is unconstrained per-market until D-2 hits the directional cap.

**Verdict:** safe after CB and D-3 stabilize. Watch `imbalance_override_applied` event rate and the direction-limit hit rate.

#### FLIP_HUNTER_FAST_TOPUP_ENABLED — SAFE TO ENABLE SECOND

| Check | Result |
|---|---|
| Config-read failure | Logs `fast_topup_config_read_failed` and bails. Safe |
| Sub-cent fallback price | **FINDING M-1** — see §5 |
| Cooldown stamped on rejection | ✓ Cooldown set at line 964 BEFORE the approval branch — prevents rejection feedback loop |
| Top-up bypasses `_process_candidate` guards | Intentional. 13-step risk gate inside `TradeEngine.execute` still applies (Kelly, per-trade cap, daily loss) |
| Top-up size cap | `min(\|imbalance\|, just_filled_size_usdc)` — never escalates above lead entry size |
| D-2 + D-3 stacked behavior | If D-2 flipped the lead side, D-3 immediately targets the now-lagging opposite side. Two positions per market possible, bounded by Kelly + per-trade cap |

**Verdict:** safe to flip second (after CB). Watch `fast_topup_fired` and `fast_topup_rejected` per user/hour. Confirm no per-market position counts exceed 2.

#### CLOSE_SWEEP_DUAL_LEG_ENABLED — SAFE TO ENABLE LAST

| Check | Result |
|---|---|
| Timing window | close_sweep fires in final 35s; both lead and top-up land in this window. Paper fills are instant |
| Spread gate bypass on top-up leg | **FINDING M-2** — see §5 |
| Exit behavior of top-up position | Top-up persists with `active_preset="close_sweep"`. exit_watcher reads from `user_settings` JOIN → inherits close_sweep force-exit timing |
| Resolver independence | `_resolve_eligible_topup_presets` correctly resolves D-3 OFF + D-4 ON (and every other combination) |

**Verdict:** safe to flip last, in PAPER only. M-2 spread-gate bypass means the close_sweep top-up may execute at a price reflecting the thin-book final-35s environment without the spread check the lead entry enforced. Acceptable for paper observation. **Must be hardened before live.**

### Recommended enablement order

```
1. BANKROLL_CIRCUIT_BREAKER_ENABLED=true
   → observe 24h; confirm skipped_circuit_breaker rate near zero

2. FLIP_HUNTER_FAST_TOPUP_ENABLED=true
   → watch fast_topup_fired / fast_topup_rejected per user/hour
   → confirm per-market position counts ≤ 2

3. SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED=true
   → watch imbalance_override_applied events
   → confirm direction-limit hit rate sane

4. CLOSE_SWEEP_DUAL_LEG_ENABLED=true   (PAPER only; harden before live)
   → watch dual-leg close_sweep pairs (lead/top-up price delta)
   → diagnose M-2 risk in real numbers before any live flip
```

Each independent — operator may pause between steps.

---

## 5. Known issues

### M-1 (MEDIUM) — Sub-cent fallback price unguarded in `_maybe_fire_fast_topup`

- **Problem found:** When `get_live_market_price` returns None (e.g. lagging leg has no CLOB bid at top-up time), `_maybe_fire_fast_topup` falls back to `market.get("yes_price")` / `market.get("no_price")` from the DB. These are Gamma-synced values that can be sub-cent (e.g. 0.505) in early-session candle markets — the same class of stale data that caused the original flip-hunter-stale-price-fix lane.
- **Root cause:** `signal_scan_job.py:892-897` — fallback path lacks the tick-alignment check that step 3b-i applies on the lead entry path.
- **Risk level:** LOW in PAPER (capital bounded by Kelly + per-trade cap), HIGH before LIVE.
- **Technical impact:** A close_sweep / safe_close / flip_hunter top-up could execute at a stale Gamma seed price (e.g. 0.505) when the lagging leg has no real CLOB activity. Paper P&L diverges from realistic fill, but no real capital loss.
- **Recommended solution:** Apply the same tick guard inside `_maybe_fire_fast_topup` for candle markets — if the resolved fallback price isn't on the 0.01 tick and the market slug contains `"updown"`, log `fast_topup_skipped` (reason=`stale_fallback_price`) and return without firing. ~5 lines, no API surface change.
- **Files affected (proposed):** `services/signal_scan/signal_scan_job.py:892-897` plus 2–3 hermetic tests.
- **Validation performed:** Code path traced; no current test exercises the None-return + DB-fallback branch for candle markets.

### M-2 (MEDIUM) — Close_sweep top-up bypasses `CLOSE_SWEEP_MAX_LEG_SPREAD`

- **Problem found:** `_maybe_fire_fast_topup` deliberately bypasses every gate in `_process_candidate` (TOB freshness, spread gate, sub-cent, fill-band). For D-3 (safe_close / flip_hunter) this is acceptable — those presets enter earlier in the candle where the spread gate isn't the dominant risk. For D-4 (close_sweep) it is not — close_sweep fires in the final 35s where the spread gate (`close-sweep-spread-gate` lane) was added specifically to defend against thin-book slippage.
- **Root cause:** `_maybe_fire_fast_topup` is preset-agnostic. The close_sweep-specific spread guard wired into `_resolve_preset_params` only fires on the scan path, not the top-up path.
- **Risk level:** LOW in PAPER (paper fills at stated price; no real spread cost), HIGH before LIVE with `CLOSE_SWEEP_DUAL_LEG_ENABLED=true`.
- **Technical impact:** A close_sweep top-up may stamp a TradeSignal with a price that survives Kelly + per-trade cap but reflects a wide-spread thin-book moment. In paper this only distorts reported P&L; in live this would cost real slippage.
- **Recommended solution:** Add a spread check inside `_maybe_fire_fast_topup` scoped to `preset == "close_sweep"` — fetch best_bid/best_ask for the lagging leg and skip the top-up if `ask - bid > CLOSE_SWEEP_MAX_LEG_SPREAD`. Mirrors the lead-entry gate's defence-in-depth.
- **Files affected (proposed):** `services/signal_scan/signal_scan_job.py` `_maybe_fire_fast_topup`, plus 2–3 hermetic tests.
- **Validation performed:** Code path traced; lead-entry gate at `domain/strategy/strategies/late_entry_v3.py` evaluates the spread; top-up path bypasses it by construction.

### No critical issues found.

---

## 6. What is next

**Immediate (operator action — when paper stats validate):**

1. Flip `BANKROLL_CIRCUIT_BREAKER_ENABLED=true` in Fly secrets. Observe 24h.
2. Flip `FLIP_HUNTER_FAST_TOPUP_ENABLED=true`. Observe.
3. Flip `SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED=true`. Observe.
4. Flip `CLOSE_SWEEP_DUAL_LEG_ENABLED=true`. Observe (PAPER only; do not pair with live mode until M-2 is fixed).

**Hardening backlog (recommended lane before any of the four go LIVE):**

- `WARP/R00T/fast-topup-tick-guard` — close M-1: tick-alignment guard on the `_maybe_fire_fast_topup` fallback price path for candle markets.
- `WARP/R00T/close-sweep-dual-leg-spread-guard` — close M-2: per-leg spread check inside `_maybe_fire_fast_topup` for `close_sweep` preset.

Both are NARROW INTEGRATION, well-scoped (~5–15 lines + tests each).

**Operational backlog (already documented in state):**

- DB_POOL_MAX 48h watch (low-severity Sentry).
- `MAX_CONCURRENT_TRADES=5` dead vs per-profile cap (WARP🔹CMD policy call).
- WithdrawModal / LiveActivationModal / DepositModal z-index sweep (flagged in `admin-drawer-mobile-friendly` known-issues).

### Suggested Next Step

Operator: proceed with enablement order in §4 once paper stats validate. WARP🔹CMD: schedule the M-1 + M-2 hardening lane before any operator considers flipping `EXECUTION_PATH_VALIDATED=true` for any of these flagged lanes.

---

**WARP•R00T self-validated.** No code modified. Read-only audit only.
