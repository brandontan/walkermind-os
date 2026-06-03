# WARP•FORGE — Open-position limit is per-user (no global ceiling)

Branch: WARP/ROOT/open-position-per-user
Tracker: follow-up to WARP-56 (max-concurrent) — owner directive 2026-06-03
Date: 2026-06-03 Asia/Jakarta

Owner (TheBoss) directive: *"biar setting masing-masing user aja, jgn jadi
setting global"* — open-position capacity must follow each user's own setting,
not a global ceiling. Decision (asked + confirmed): **per-user penuh, tanpa
ceiling** (no absolute system backstop). This REVERSES WARP-54 Lane 2, which had
clamped every user to a hard global 5.

---

## 1. What was built

Concurrent open-position capacity is now a PER-USER limit with no global ceiling:

- `effective_max_concurrent(profile, override)` rewritten: the user's
  `max_concurrent_override` is authoritative when validly set (≥1) and may raise
  OR lower the limit; otherwise the profile default applies (conservative 5 /
  balanced 12 / aggressive 20 / custom 12). The previous `min(5, profile,
  override)` clamp is gone — a non-positive/unparseable override falls back to the
  profile default (never bricks the user). Bound only by the existing
  `user_settings` DB CHECK (1..20) at write time.
- The `MAX_CONCURRENT_TRADES = 5` constant was REMOVED (it was the global ceiling).
- Gate Cap 4 (`validate_risk_caps`, open-position count) no longer clamps to
  `min(MAX_OPEN_POSITIONS, 5)`. It now takes a `max_open_cap` argument; `evaluate()`
  passes the per-user `effective_max_concurrent` so Cap 4 enforces the user's own
  limit. Direct callers that omit it fall back to `settings.MAX_OPEN_POSITIONS`.
- Gate step 7 + `resume_safety_check` step 7 already call `effective_max_concurrent`
  → they inherit the per-user behavior automatically.

All other capital brakes are untouched: Kelly 0.25, max position ≤10%, daily-loss
−$2,000, drawdown >8%, correlated-exposure 40% (step 8), kill switch,
`ENABLE_LIVE_TRADING`. Paper-only.

## 2. Current system architecture (relevant slice)

```
RISK gate (domain/risk/gate.py):
  Cap 4 (validate_risk_caps, runs before step 7):
      open_cap = max_open_cap (per-user effective)  ← from evaluate()
               | fallback settings.MAX_OPEN_POSITIONS (direct callers)
      reject if open_count >= open_cap
  step 7:
      max_concurrent = effective_max_concurrent(profile, override)
      reject if cur >= max_concurrent
  (resume_safety_check re-runs step 7 only — Cap 4 not in that path)

effective_max_concurrent(profile, override)  [domain/risk/constants.py]:
  override (≥1)  -> override          # authoritative; may raise or lower
  else           -> PROFILES[profile]["max_concurrent"]  # 5 / 12 / 20 / 12
  # no global clamp; MAX_CONCURRENT_TRADES constant removed
```

In the full `evaluate()` path Cap 4 fires first at the count limit (same per-user
value as step 7); step 7 remains the sole enforcer on the `resume_safety_check`
path. Both use the identical per-user value, so enforcement is consistent.

## 3. Files created / modified (full repo-root paths)

Modified:
- projects/polymarket/crusaderbot/domain/risk/constants.py (remove
  MAX_CONCURRENT_TRADES; rewrite effective_max_concurrent to per-user)
- projects/polymarket/crusaderbot/domain/risk/gate.py (Cap 4 per-user via
  max_open_cap arg; evaluate() threads effective_max_concurrent)
- projects/polymarket/crusaderbot/tests/test_concurrency_policy.py (rewritten to
  the per-user policy)
- projects/polymarket/crusaderbot/tests/test_complete_set_scan.py (mock
  `_caps_ok` accepts the new max_open_cap kwarg)
- AGENTS.md (RISK CONSTANTS table — max concurrent now per-user)
- docs/blueprint/crusaderbot.md (§6 constants block + profile table reconciled to
  code truth 5/12/20 + gate step 12 wording)

Created:
- projects/polymarket/crusaderbot/reports/forge/open-position-per-user.md (this report)

## 4. What is working

- 287 touched-subsystem tests pass (concurrency policy rewritten 19, risk-limit
  reconciliation, warp54 lanes, resume_safety_check, live-gate, process-candidate,
  signal-scan, complete-set, runtime smoke, warp56-sentry, kill-switch,
  robustness). ruff + py_compile clean on all touched files.
- Unit: profile defaults 5/12/20/12; override authoritative (raise + lower);
  no-ceiling proven (override 999 → 999); defensive fallback for 0/neg/unparseable.
- Integration: a balanced user with override 18 and 15 open positions now PASSES
  (was blocked under the old 5/12 clamp); resume path with conservative+override
  999 passes at 5 open.

## 5. Known issues

- This REVERSES WARP-54 Lane 2 and removes a `MAX_CONCURRENT_TRADES` invariant that
  was pinned in AGENTS.md + blueprint §6. Those docs are updated in this lane so a
  future agent does not re-introduce the global clamp citing the old hard rule.
- Practical upper bound today is the `user_settings` DB CHECK (1..20); raising a
  user above 20 would need a migration to that constraint (NOT in this lane).
- Cap 4 and step 7 are now redundant in the `evaluate()` path (same per-user
  value; Cap 4 fires first). Kept as defense-in-depth — step 7 is still required
  for `resume_safety_check`, which does not run Cap 4.
- MAJOR tier (risk gate) — loosens a capital-safety limit per owner decision;
  other brakes (Kelly/position/loss/drawdown/correlated-40%/kill) intact; paper-only.

## 6. What is next

- WARP•SENTINEL validation (MAJOR, risk path) before merge — or WARP🔹CMD/owner
  merge decision (owner directed + holds merge authority).
- After merge: Fly redeploy (changes live gating — users may now run up to their
  own configured concurrent limit).
- Optional follow-up: if the owner wants per-user values >20, raise the
  `user_settings.max_concurrent_override` DB CHECK (migration) + the WebTrader/
  Telegram override input max.

---

Validation Tier   : MAJOR (risk gate / concurrent-position limit)
Claim Level       : FULL RUNTIME INTEGRATION (changes live gating behavior)
Validation Target : effective_max_concurrent per-user semantics; gate Cap 4 +
                    step 7 + resume_safety_check consume the per-user value; no
                    global ceiling; other risk constants untouched
Not in Scope      : DB CHECK (1..20) widening; WebTrader/Telegram override input
                    max; any other risk constant
Suggested Next    : WARP•SENTINEL (MAJOR) → owner merge → Fly redeploy
