# WARP-95 — Decouple signal_following + Restore 5m/15m Support

Role: WARP•R00T
Branch: WARP/decouple-signal-following
Validation Tier: MAJOR (production incident — orchestrator user-load + scan timeframe)
Claim Level: NARROW INTEGRATION
Validation Target: the two outage defects — signal_following=OFF killing the whole
  orchestrator, and the WARP-93 candle_auto 5m hard-pin stopping 15m scanning.
Not in Scope: trading/exit/TP-SL/slippage logic, wallet code (WARP-94),
  ENABLE_LIVE_TRADING / SCORER_ACTIVE / ORCHESTRATOR_ACTIVE / kill_switch, migrations.
Suggested Next Step: WARP🔹CMD sign-off (directive Stop Condition: MAJOR → CMD
  merge sign-off). Not self-merged.

---

## 1. What was built

Two minimal, root-caused fixes (one commit per issue).

### Issue 1 — signal_following=OFF killed Smart Strike. Root cause CORRECTED.
The directive attributed this to "the WARP-93 guard was too broad." That is not
the cause — the WARP-93 Issue-4 guard lives in the LEGACY `scheduler.run_signal_scan`
(copy_trade path) and never touches the new orchestrator's `late_entry_v3` flow.
The real coupling is PRE-EXISTING (P3d design): `signal_scan_job._load_enrolled_users`
— the single user-loading query for the ENTIRE orchestrator (candle_auto,
close_sweep, safe_close, flip_hunter, weather, playbook) — INNER-JOINed the
`signal_following` enrolment row (`us.strategy_name='signal_following' AND
us.enabled=TRUE`) AND added an anti-join `NOT EXISTS (strategies st WHERE
st.name='signal_following' AND st.enabled=FALSE)`. So flipping the `signal_following`
operator switch OFF in the `strategies` table returned ZERO users → the orchestrator
scanned nobody → no late_entry_v3, no factor_vectors (the 5.5h outage; factor_vectors
last write 07:20:49, signal_following disabled 07:21:03).

Fix: load users by `auto_trade_on=TRUE AND paused=FALSE` off the `users` table;
LEFT JOIN the `signal_following` enrolment row PURELY to preserve the legacy
`us.weight` sizing fallback (NULL when unenrolled — `s.capital_alloc_pct` is the
primary anyway). Per-strategy gating is unchanged and already correct downstream:
`_preset_allows(active_preset, <strategy>)` honours the per-strategy operator
toggle via `_GLOBALLY_DISABLED_STRATEGIES` (refreshed each tick by
`_refresh_disabled_strategies` from the same `strategies` table). So each strategy
toggle now gates ONLY itself: disabling signal_following blocks only its (already
dormant) Phase C feed; disabling late_entry_v3 blocks only late_entry_v3. As a
bonus this also closes the WARP-75 "opted-in but unenrolled" coverage gap (such
users were silently excluded by the old INNER JOIN).

### Issue 2 — WARP-93 candle_auto 5m hard-pin stopped 15m scanning.
WARP-93 Issue 2 added a pin in `router.activate_preset`: for `candle_auto`, any
requested timeframe ≠ 5m was overwritten to 5m. Combined with the web UI
re-POSTing the preset on activation, this silently flipped every 15m candle_auto
user to 5m → 15m factor_vectors stopped (last 07:15 UTC). The boss directive now
states both 5m and 15m are live and must be honoured per user.

Fix: remove the pin — `timeframe = body.selected_timeframe or "5m"` (NULL → 5m
default, unchanged). The orchestrator already scans each user's `selected_timeframe`
(signal_scan_job loads `s.selected_timeframe` and the scan uses
`selected_timeframe or "5m"`), so a 15m user resumes 15m scanning the moment the
pin is gone. No scan-side change needed.

### UI (Issue 2, directive's 3rd commit) — NOT NEEDED.
The AUTO-tab timeframe control (`AutoTradePage.tsx` ~L888) renders BOTH 5m and 15m
buttons with NO `disabled` attribute; `handleSelectTimeframe` does not block 15m.
The 15m button was never code-disabled — the "disabled" symptom was purely the
backend pin reverting the selection (click 15m → backend forced 5m → reload showed
5m). With the pin removed the button is functional. No frontend change was made
(fabricating one would be dead code).

## 2. Current system architecture

DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING (unchanged).
- The orchestrator (`signal_scan_job.run_once`) loads ALL auto-trading users once
  per tick (`_load_enrolled_users`, now decoupled), then per user dispatches to the
  strategy permitted by `active_preset` via `_preset_allows` — each branch
  independently gated by the per-strategy operator toggle. candle_auto → late_entry_v3
  is fully independent of the signal_following toggle.
- Timeframe: per-user `selected_timeframe` (5m | 15m) drives which crypto candle
  markets are scanned; `activate_preset` persists the user's choice without override.

## 3. Files created / modified (full repo-root paths)

Modified:
- projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py — `_load_enrolled_users` decoupled from signal_following (Issue 1)
- projects/polymarket/crusaderbot/webtrader/backend/router.py — removed candle_auto 5m pin in `activate_preset` (Issue 2)
- projects/polymarket/crusaderbot/tests/test_admin_console.py — rewrote the stale loader-coupling pin into a decoupling regression guard
- projects/polymarket/crusaderbot/tests/test_candle_auto_timeframe_pin.py — now asserts candle_auto respects selected_timeframe (5m & 15m)

Created:
- projects/polymarket/crusaderbot/tests/test_warp95_decouple_signal_following.py (Issue 1, 4 tests)
- projects/polymarket/crusaderbot/reports/forge/decouple-signal-following.md (this report)

## 4. What is working

- Targeted sweep: signal_scan_job + admin_console + auto_trade_consent + pipeline
  + runtime_trade_smoke + demo_polish + signal_following + candle_auto_router +
  the 2 WARP-95 test files — all pass (>350 tests across the touched modules),
  ruff clean.
- Issue 1: `_load_enrolled_users` SQL decoupled (FROM users, gated on auto_trade_on,
  no strategies anti-join); `_preset_allows` proves candle_auto→late_entry_v3 stays
  True with signal_following globally disabled, and goes False only when
  late_entry_v3 itself is disabled (per-strategy independence).
- Issue 2: candle_auto + 15m persists 15m; + 5m persists 5m; + NULL → 5m;
  close_sweep + 15m unchanged.

## 5. Known issues

- Data remediation (operator, NOT code): users whose `selected_timeframe` was
  silently flipped to 5m by the WARP-93 pin during the incident window stay at 5m
  until they re-select 15m (or an operator resets them). The directive's acceptance
  criteria name walk3r69=15m / qwneer8=5m as the intended states — CMD/operator
  sets those. No migration was added (directive scope: no schema/data migration).
- signal_following remains DORMANT (no operator feed publishes; no preset maps to
  it) — unchanged by this lane; its Phase C is still correctly gated.

## 6. What is next

- WARP🔹CMD sign-off (MAJOR Stop Condition). Not self-merged.
- After deploy, verify DB:
  `SELECT timeframe, MAX(updated_at) FROM factor_vectors GROUP BY timeframe;` —
  both 5m and 15m should show recent timestamps; and toggling signal_following OFF
  must NOT stop late_entry_v3 factor_vectors.
