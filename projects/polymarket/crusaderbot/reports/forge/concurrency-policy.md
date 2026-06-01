# WARP•R00T — concurrency-policy (Lane 3C)

**Branch:** `WARP/ROOT/concurrency-policy`
**Role:** WARP•R00T (system hardening)
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** the risk-gate concurrent-trades cap (gate step 7 + `resume_safety_check` step 7) — closes C-3 by ratifying per-profile defaults (5/12/20) **and** giving each user a tighter-only override (`user_settings.max_concurrent_override`). Multi-user: each user controls their own risk/reward.
**Not in Scope:** Kelly fraction per-user override, max-position-pct per-user override (already governed by `MAX_SINGLE_POSITION_PCT` × profile.max_pos_pct), C-4 `_process_candidate` decomposition, LIVE live-fire validation.

---

## 1. What was built

C-3 ("`MAX_CONCURRENT_TRADES=5` dead vs per-profile 5/12/20") closed by ratifying the per-profile defaults **and** exposing a per-user override that can only tighten — never loosen — the profile cap. This is the same most-restrictive pattern used by `daily_loss_override` and `max_drawdown_pct`. The bot is multi-user; each user sets their own risk/reward within the safety envelope their chosen profile permits.

Three changes:

- **Dead constant removed.** `MAX_CONCURRENT_TRADES = 5` deleted from `domain/risk/constants.py`. Grep confirms zero references outside the definition site. Gate step 7 has always read `profile["max_concurrent"]`; the file-top constant was a misleading vestige.

- **Per-profile audit coverage added.** `hardening.audit_risk_constants` now validates each profile's `max_concurrent` value against `1 ≤ v ≤ 50`. Defends against a mis-typed `0`, `-1`, or `500` that would silently poison step 7. Two new boundary tests cover zero and over-ceiling violations.

- **Per-user override added** (`max_concurrent_override`). New `user_settings` column (migration 077) with a DB CHECK enforcing `NULL OR 1..20`. New helper `effective_max_concurrent(profile, user_override)` picks `min(profile_default, user_override)`. Gate step 7 and `resume_safety_check` step 7 consume it. New API field on `GET /api/web/strategy` (echoed back), validated on `POST /api/web/customize` (rejects out-of-range with 400). `TradeSignal` carries the value through the signal pipeline so the gate sees it on both fresh signals and crash-recovery resume.

## 2. Current system architecture

```
user sets max_concurrent_override (1..20) via POST /api/web/customize
  → user_settings.max_concurrent_override (DB CHECK: 1..20 or NULL)
  → signal_scan SELECT s.max_concurrent_override
  → TradeSignal.max_concurrent_override
  → GateContext.max_concurrent_override
  → effective_max_concurrent(profile, override) = min(profile.max_concurrent, override)
  → gate step 7  AND  resume_safety_check step 7
```

Most-restrictive semantics enforced at three layers (defence in depth):
- DB CHECK constraint rejects values outside [1, 20]
- API router rejects values outside [1, 20] with HTTP 400
- Helper coerces invalid (zero/negative/non-numeric) values to "ignored" so legacy rows can't brick a user

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/domain/risk/constants.py` — removed dead `MAX_CONCURRENT_TRADES`; added `effective_max_concurrent(profile, user_override)` helper
- `projects/polymarket/crusaderbot/domain/risk/hardening.py` — added `max_concurrent` audit (1..50) per profile in `audit_risk_constants`
- `projects/polymarket/crusaderbot/domain/risk/gate.py` — added `max_concurrent_override` field on `GateContext`; gate step 7 calls `K.effective_max_concurrent`; `resume_safety_check` accepts `max_concurrent_override` kwarg and step 7 uses it
- `projects/polymarket/crusaderbot/services/trade_engine/engine.py` — added `max_concurrent_override` field on `TradeSignal`; passed into `GateContext`
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` — SELECT now fetches `s.max_concurrent_override`; mapped onto both `TradeSignal` construction sites and the `_resume_safety_check` call
- `projects/polymarket/crusaderbot/webtrader/backend/schemas.py` — `StrategyResponse` echoes `max_concurrent_override`; `CustomizeRequest` accepts it
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` — GET `/strategy` SELECTs + echoes the field; POST `/customize` validates `1 ≤ v ≤ 20`
- `projects/polymarket/crusaderbot/tests/test_live_gate_hardening.py` — 2 new audit-boundary tests
- `projects/polymarket/crusaderbot/tests/test_admin_console.py` — `_settings_row` mock fixture includes the new column

Created:
- `projects/polymarket/crusaderbot/migrations/077_user_max_concurrent_override.sql` — additive, idempotent `ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS …`
- `projects/polymarket/crusaderbot/tests/test_concurrency_policy.py` — 15 hermetic tests (helper unit, gate step 7, resume step 7, dead-constant assertion, per-profile range invariants)
- `projects/polymarket/crusaderbot/reports/forge/concurrency-policy.md` — this report

## 4. What is working

- `pytest tests/test_concurrency_policy.py` — 15/15 pass
- `pytest tests/test_live_gate_hardening.py` — 37/37 pass (35 baseline + 2 new audit-boundary tests)
- `pytest tests/test_admin_console.py` — 56/56 pass (mock fixture corrected)
- Full project suite: **2228 passed**. Only the 3 pre-existing SDK-gap failures remain (`poly_eip712_structs`, `web3.py` Safe address) — same baseline as merged Lanes 1+2. Zero regression introduced.
- Migration 077 is additive, idempotent, and safe to deploy ahead of code (NULL default = old behaviour). No data backfill required.
- Helper behaviour verified by smoke test:
  - `effective_max_concurrent('balanced', None)` → 12 (profile default)
  - `effective_max_concurrent('balanced', 3)` → 3 (user tighter wins)
  - `effective_max_concurrent('aggressive', 100)` → 20 (profile floor — user cannot loosen)
  - `effective_max_concurrent('conservative', 0)` → 5 (defensive: invalid override ignored)

## 5. Known issues

- The Telegram bot does not yet expose a setter for `max_concurrent_override`. WebTrader API is the only entry point; CLI/keyboard parity is a follow-up (low-risk, can ship after first LIVE).
- Front-end form binding for the new field is not in this lane — backend wiring only. The field is echoed on `GET /api/web/strategy` ready for the form to read.
- The `audit_risk_constants` per-profile ceiling (50) is a sanity guard, not a policy cap. If a future profile ratifies a higher concurrent cap, raise the audit ceiling at the same time.

## 6. What is next

- **C-4 — Decompose `_process_candidate`** (~600 lines, `services/signal_scan/signal_scan_job.py`). STANDARD tier, no safety impact, zero policy decisions needed.
- **WebTrader UI** — add a "Max concurrent trades" field to the customize form (read from `max_concurrent_override`, POST back when changed).
- **Telegram parity** — add `/max_concurrent <N>` command + inline keyboard step alongside the existing risk-profile flow.
- **Lane 5 — LIVE live-fire validation** — `USE_REAL_CLOB=True` end-to-end with a small cap, then flip `EXECUTION_PATH_VALIDATED`. MAJOR tier, owner-gated + SENTINEL required.
- **Pre-LIVE env tuning** (operator step before flip): relax `MAX_DAILY_LOSS_USD` and `MAX_TOTAL_EXPOSURE_PCT` so per-profile / per-user limits become the visible truth at LIVE.

---

**Suggested Next Step:** WARP🔹CMD review of `WARP/ROOT/concurrency-policy` (STANDARD, NARROW INTEGRATION). Migration 077 is safe to deploy on its own; per-user override behaviour activates the moment the deploy lands and users set a value.
