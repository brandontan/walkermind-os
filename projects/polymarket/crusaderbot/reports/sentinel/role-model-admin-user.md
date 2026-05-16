# WARP•SENTINEL Report — role-model-admin-user

Branch: WARP/role-model-admin-user
Date: 2026-05-17 17:30 Asia/Jakarta
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: two-role model (admin + user); paper-open change does not
  weaken any LIVE safety path; assert_live_guards (Tier-4 + activation guards)
  intact; risk-gate step-3 still blocks live for tier<3; no production handler
  relies on removed tier wording.
Not in Scope: DB schema teardown (not done); config.py ENABLE_LIVE_TRADING
  default fix (WARP/crusaderbot-finalize, PR #1075); PR merge.

---

## Phase 0 — Pre-Test (STOP if any fail)

- Forge report at correct path (reports/forge/role-model-admin-user.md) ✅
- All 6 mandatory sections present ✅
- PROJECT_STATE.md updated (2026-05-17 16:00) ✅
- No phase*/ folders introduced ✅
- Domain structure correct ✅
- Implementation evidence exists for critical layers ✅
- CI: 2 × "Lint + Test" completed — SUCCESS (runs 25971309947, 25971309004) ✅

---

## Phase 1 — Functional Testing

### 1a. Paper-open gate

File: `projects/polymarket/crusaderbot/domain/risk/gate.py:176`

```python
if ctx.trading_mode == "live" and ctx.access_tier < 3:
```

Before: tier check applied unconditionally → paper users without tier 2+ were blocked.
After: tier check scoped to `trading_mode == "live"` only → paper passes for every user.

Verdict: PASS. Paper is genuinely open. The AND condition correctly preserves
live defence-in-depth (tier < 3 blocks live at step-3).

### 1b. Setup gate removal

File: `projects/polymarket/crusaderbot/bot/handlers/setup.py:31`

`_ensure_tier2` renamed to `_ensure_user`; tier check removed; all 9 call sites
updated. The function now only upserts the user and returns (user, True) for any
authenticated Telegram user.

Verdict: PASS. No gate on onboarding flow; every authenticated user can complete
setup.

### 1c. Decorator audit (critical)

Grep of all production handler modules under `bot/handlers/`:
- `@require_tier` occurrences: 0 (zero)
- `@require_access_tier` occurrences: 0 (zero)

No production handler is gated by a tier decorator. The wording change has no
gating side-effect; it only changes the message sent when decorators fire in tests.

Verdict: PASS.

### 1d. Wording canonicalisation

- `access_tier.py:28-29` — `_UPGRADE_MESSAGES` = {TIER_PREMIUM: "This feature is not available.", TIER_ADMIN: "Admin access required."}; fallback = "This feature is not available."
- `tier_gate.py:36` — `TIER_DENIED_MESSAGE = "This feature is not available."`
- `bot/tier.py:12-14` — `TIER_MSG` = {2: "…not available.", 3: "…not available.", 4: "…not available."}
- `allowlist.py:18-20` — `_TIER_LABELS` = {1: "User", 2: "User"}
- `admin.py` user-facing messages: verified via reply_text/reply_html grep — no residual "Operator / Tier 2/3/4 / allowlist / premium" in user-facing strings
- `scheduler.py:230-234` deposit watcher: "Your balance is credited and ready." / "Credited. Live trading needs a minimum balance of $X USDC (paper auto-trade is always available)."

Verdict: PASS. Two canonical messages enforced. Infrastructure uses of
`actor_role="operator"` in audit.write are internal-only (correct per scope).

### 1e. Admin surface

- `admin.py` `_ADMIN_HELP` relabelled to `🛠 Admin` panel (Runtime Health / User Monitor / Emergency Stop / Logs / Roles / Broadcast)
- `/admin settier` accepts `user|admin` → `_ROLE_MAP = {"USER": "FREE", "ADMIN": "ADMIN"}` (module-level constant, hoisted per Gemini review b7457a7)
- Stats: "Roles — Users: {free_n + premium_n} · Admins: {admin_n}" (maps FREE+PREMIUM headcount to "Users")
- Tests: 32 access-tier tests pass including updated 3 tests (user|admin wording, "Invalid role", "🛠 Admin")

Verdict: PASS.

### 1f. Full test suite

Result: **1413 passed, 1 skipped, 21 warnings** (pre-existing warnings only)
ruff E9,F63,F7,F82 on all 10 changed files: **All checks passed!**

---

## Phase 2 — Pipeline End-to-End

Execution pipeline for live-mode attempt:

```
gate.py (step-3 blocks tier<3 for live)
  → router.py:35  assert_live_guards (guard 1 — blocks if any flag false or tier<4)
    → live.py:116 assert_live_guards (guard 2 — identical check, inside execute)
      → live_engine.execute (CLOB order)
```

Execution pipeline for paper-mode:

```
gate.py (step-3 passes — trading_mode != "live")
  → router.py (chosen_mode == "paper" → _paper directly)
    → paper engine (no live guards consulted)
```

Verdict: PASS. No stage skipped. Paper path does not consult live guards at all.

---

## Phase 3 — Failure Modes

### Live attempt by paper user (tier 1-2)

- gate.py step-3: `"live" and tier < 3` → blocked at gate before reaching router ✅
- (if gate bypassed hypothetically) router.py:35 assert_live_guards: `tier < 4` → LivePreSubmitError → paper fallback ✅
- (if router bypassed hypothetically) live.py:116 assert_live_guards: same check → LivePreSubmitError ✅

All three checkpoints independently block the live path. Defence-in-depth is intact.

### ENABLE_LIVE_TRADING default (pre-existing, NOT introduced by this lane)

`config.py:143` still has `ENABLE_LIVE_TRADING: bool = True`. This is NOT introduced
by this PR — it predates the lane and is tracked in PR #1075 (crusaderbot-finalize,
HELD). fly.toml forces ENABLE_LIVE_TRADING=false in production, making the code
default irrelevant to production posture. SENTINEL notes it but does not block on it
as it is out of scope for this lane.

Both live guards (router.py:35 + live.py:116) call `assert_live_guards`, which
checks `EXECUTION_PATH_VALIDATED: bool = False` (default) — so even with
ENABLE_LIVE_TRADING defaulting True in test environments, the EXECUTION_PATH_VALIDATED=false
check independently blocks live execution in all default-env runs.

Verdict: PASS for this lane. Pre-existing default risk mitigated by secondary guard.

### assert_live_guards guard completeness (live.py:48-71)

1. `ENABLE_LIVE_TRADING=false` → LivePreSubmitError ✅
2. `EXECUTION_PATH_VALIDATED=false` → LivePreSubmitError ✅
3. `CAPITAL_MODE_CONFIRMED=false` → LivePreSubmitError ✅
4. `ENABLE_LIVE_TRADING=true AND USE_REAL_CLOB=false` → LivePreSubmitError ✅
5. `access_tier < 4` → LivePreSubmitError ✅
6. `trading_mode != "live"` → LivePreSubmitError ✅

All six conditions verified intact. No regression introduced by this PR.

---

## Phase 4 — Async Safety

No new concurrent state mutations introduced. `_ensure_user` is an idempotent
upsert (pre-existing pattern). `_ROLE_MAP` is a module-level constant
(no shared mutable state). Risk gate, router, and live engine are unchanged.

Verdict: PASS.

---

## Phase 5 — Risk Rules

| Rule | Value | Status |
|---|---|---|
| Kelly fraction a | 0.25 (unchanged) | ✅ |
| Max position size | ≤10% of capital (unchanged) | ✅ |
| Daily loss limit | -$2,000 (gate.py step-5, unchanged) | ✅ |
| Drawdown circuit-breaker | >8% auto-halt (unchanged) | ✅ |
| Signal deduplication | unchanged | ✅ |
| Kill switch | Telegram-accessible, unchanged | ✅ |
| assert_live_guards (Tier 4 + 5 env flags) | INTACT at live.py:48-71 | ✅ |
| Risk gate step-3 for live | INTACT at gate.py:176 | ✅ |

Verdict: PASS. No risk rule weakened.

---

## Phase 6 — Latency

No new I/O paths, DB queries, or network calls introduced by this lane. All
changed code is synchronous string mapping or conditional guard adjustments.

Verdict: PASS.

---

## Phase 7 — Infrastructure

- No DB schema changes (no migration) ✅
- OPERATOR_CHAT_ID routing and `_is_operator()` function intact — infrastructure not user-facing ✅
- `audit.actor_role="operator"` values preserved in audit log writes (internal tracking) ✅
- allowlist.py async-safe in-memory store unchanged ✅
- readiness_validator.py:171 existence check for `assert_live_guards` still resolves ✅
- No fly.toml changes; production env overrides unchanged ✅

Verdict: PASS.

---

## Phase 8 — Telegram UX

User-facing message inventory after this lane:

| Scenario | Message |
|---|---|
| Non-admin hits admin command | `Admin access required.` |
| Feature unavailable | `This feature is not available.` |
| Deposit credited (no min) | `Your balance is credited and ready.` |
| Deposit credited (min set) | `Credited. Live trading needs a minimum balance of $X USDC (paper auto-trade is always available).` |
| Admin settier success | `<user> is now <role>.` |
| Admin settier bad role | `Invalid role '<x>'. Use: user \| admin` |

All messages are clean. No tier numbers, operator labels, or allowlist/premium
wording visible to regular users.

Verdict: PASS.

---

## Critical Issues

**None found.**

---

## Stability Score

| Domain | Weight | Score | Notes |
|---|---|---|---|
| Architecture | 20% | 18/20 | Two-role model clean; dual tier tables retained by design |
| Functional | 20% | 20/20 | Paper open; 1413 tests pass; zero decorator regressions |
| Failure modes | 20% | 18/20 | Triple-layer live block; pre-existing ENABLE_LIVE_TRADING default (out of scope) noted |
| Risk rules | 20% | 20/20 | assert_live_guards 6-check intact; risk gate step-3 scoped correctly |
| Infra + Telegram | 10% | 9/10 | No infra change; wording verified clean |
| Latency | 10% | 10/10 | No new I/O |
| **Total** | | **95/100** | |

---

## GO-LIVE STATUS

**DECISION: PASS — CLEAR TO MERGE**

Score: 95/100. Zero critical issues.

The paper-open change (`gate.py:176`) is correct and safe: it adds a
`trading_mode == "live"` precondition so tier-based blocking only applies
when a user actually requests live execution. Paper paths never touch live
guards. The authoritative live safety boundary — `assert_live_guards` at
`live.py:48-71` — is verified intact and called in two independent locations
(router.py:35 and live.py:116). All six guard conditions (ENABLE_LIVE_TRADING,
EXECUTION_PATH_VALIDATED, CAPITAL_MODE_CONFIRMED, USE_REAL_CLOB, tier≥4,
trading_mode=live) are present and unmodified.

No activation guard was bypassed. Live trading remains OFF. Production posture
is PAPER ONLY.

---

## Fix Recommendations

No critical or blocking fixes required. Advisory only:

1. (LOW — pre-existing, tracked in PR #1075) `config.py:143`: `ENABLE_LIVE_TRADING`
   default True. Mitigated by fly.toml override + EXECUTION_PATH_VALIDATED=False
   secondary guard. Fix ships with PR #1075 (HELD, SENTINEL-PASSED 96/100).

2. (LOW — cosmetic) `tier_gate.py:19-20` docstring still mentions "Tier 2-gated
   command" — internal code comment; not user-facing; no safety impact.

---

## Deferred Backlog

- PR #1075 (crusaderbot-finalize): HELD, SENTINEL-PASSED. Merge decision with WARP🔹CMD.
- `ENABLE_LIVE_TRADING` code default alignment (WARP/config-guard-default-alignment) — tracked.
- Dual tier tables (users.access_tier + user_tiers) retained by design; DB teardown deferred.

---

## Telegram Preview

### User hits admin command

```
Admin access required.
```

### Feature unavailable

```
This feature is not available.
```

### Admin panel (/admin)

```
🛠 Admin

Runtime Health · User Monitor · Emergency Stop · Logs · Roles · Broadcast
```

---

Suggested Next Step: WARP🔹CMD merge decision — PR #1076 is SENTINEL-APPROVED,
CI green, Gemini review addressed. Merge when ready.
