# Retroactive WARP•SENTINEL Validation — PR #1688 (WARP-83 Sub-Lane E.2)

Subject: PR #1688 "honest TP/SL controls (Path C)" — head `WARP/honest-tpsl-controls`
(sha `f6bdfd84`), merged to `main` 2026-06-07 19:00 UTC by the owner WITHOUT a
WARP•SENTINEL gate (MAJOR tier). This is a RETROACTIVE validation: the code is
already merged + deployed. No code changed, no PR merged/closed, no flag flipped.
Reviewer: WARP•R00T (owner-assigned). Report for WARP🔹CMD decision.

Validation environment: dev/sandbox (Claude Code remote). DB reads are read-only
against Supabase `ykyagjdeqcgcktnpdhes` (live CrusaderBot).

---

## 1. TSX Build Result

Command: `npm install && npm run build` in `projects/polymarket/crusaderbot/webtrader/frontend`.

Result: **PASS.** `vite build` → `✓ built in 7.62s`, process EXIT=0, **zero TypeScript
errors**. All bundles emitted (AutoTradePage-*.js 124.89 kB / AdminPage 60.14 kB /
SettingsPage 63.26 kB, etc.). The `AutoTradePage.tsx` change from #1688 (TP/SL shown
informational) compiles clean.

## 2. Python Test Result

Command: `pytest projects/polymarket/crusaderbot/...`.

Result in this sandbox: **NOT RUNNABLE — environment dep gap, NOT a test failure.**
Collection aborts at import: `fastapi` is absent, and `python-telegram-bot` pulls a
broken native `cryptography` (`ModuleNotFoundError: No module named '_cffi_backend'`
→ pyo3 `PanicException`). These are runtime libraries the sandbox lacks; they do not
reflect on #1688's code.

Authoritative test signal = **CI on the merge commit**: the #1688 "Lint + Test" check
runs (run 27101820950 + 27101819639) both concluded **success** at merge
(2026-06-07 19:01 UTC). The FORGE report (`reports/forge/honest-tpsl-controls.md`)
claims 77 tests pass, including the new `test_honest_tpsl_controls.py` (200 lines) and
`test_migration_089_never_touches_positions`. CI-green at merge is consistent with
that claim. Recommendation: treat CI as the test gate of record; the sandbox cannot
reproduce it.

## 3. Code Review (MAJOR tier)

Full unified diff read (1,001 lines, 11 code/migration/test files). Checklist:

- **Free-form TP/SL bypassing EV validation — FINDING (follow-up).**
  `services/signal_scan/signal_scan_job.py:_build_trade_signal` reads
  `row.get("tp_pct")` / `row.get("sl_pct")` and assigns them to the signal with only
  a NULL→default fallback. (As of #1688's merge the fallback constant was
  `_DEFAULT_STRATEGY_TP_PCT=1.5` / `_SL=0.5`; WARP-85 — merged AFTER #1688 — later
  refactored this to a strategy-resolved `_strategy_default_tp_sl()` with a logged
  last-resort `_LAST_RESORT_TP_PCT` / `_LAST_RESORT_SL_PCT` = 1.5 / 0.5. The audit
  finding is unchanged across both: neither clamps a non-NULL user value.)
  A non-NULL value is `float()`-cast and passed through with **no numeric clamp**:
  nothing rejects `sl_pct = 0` (no stop-loss), a negative value, or an absurd
  `tp_pct`. The entry EV/edge gate (step 12, `MIN_EDGE_BPS`) gates entry edge, NOT
  the exit thresholds, so user-supplied TP/SL is genuinely ungated server-side. The
  override is auth-gated (Custom Risk profile write) and the frontend warns
  "not backtested", but there is no server-side bounds check in the diff. This is an
  unclamped capital-path input — the one item warranting a condition.
- **DB reads in hot paths — PASS.** No new per-candidate/per-tick query. TP/SL come
  from the `user_settings` row already SELECTed by the scan loop. The change actually
  REMOVED a per-rule lookup (`_candle_auto_rule_tpsl` + its `PRESETS` import).
- **ENABLE_LIVE_TRADING bypass — PASS.** No reference to the live guard / `allow_fills`
  / `MODE` anywhere; change confined to TP/SL value sourcing.
- **Threading — PASS.** No `threading`/`Thread`/`concurrent.futures`; asyncio-only.
- **Full type hints — PASS.** Production constants + resolved locals annotated
  (`_resolved_tp_pct: float`, etc.); no new untyped production functions.
- **Silent failures — PASS (improved).** Fallback is logged
  (`user_settings_tp_pct_missing_defensive_fallback`); the PR REMOVED a real silent
  swallow (`except Exception: return (None, None)` in the deleted helper).
- **Secrets / risk constants — PASS.** No hardcoded secrets. Kelly, position cap,
  daily-loss, drawdown, and per-profile `capital_alloc_pct` (0.20/0.40/0.60) unchanged.

Observations (non-blocking):
- The runtime-behavior-preservation claim is **load-bearing on deploy ordering**:
  migration 089 must land before the new scan code reads `user_settings`; out-of-order
  deploy would expose stale/NULL rows. The base PR documents this; release_command runs
  migrations before serving (per #1676 hardening), so the ordering holds in prod.
- Secondary builder paths (`fast_topup` / `safe_close`) were NOT given the NULL→default
  fallback; they pass `None` on a NULL row — benign only after 089 backfills all rows.

## 4. Migration 089 Review

File: `migrations/089_backfill_user_settings_tpsl.sql`. **PASS — data-only, idempotent,
reversible. No schema-breaking DDL.**

```sql
UPDATE user_settings SET tp_pct = 1.5, sl_pct = 0.5
 WHERE tp_pct IS DISTINCT FROM 1.5 OR sl_pct IS DISTINCT FROM 0.5;
```

- Single `UPDATE` on `user_settings` only — no `DROP` / `ALTER TYPE` / `NOT NULL` / DDL.
- Idempotent (`IS DISTINCT FROM` guard → converged re-run is a no-op).
- Rollback present (`migrations/rollback/089_..._rollback.sql`, restores 0.90/0.40), but
  **non-lossless** (pre-089 per-user custom values are overwritten, not recoverable) —
  documented in the rollback header.
- Live schema confirmed (read-only): `user_settings.tp_pct` / `sl_pct` are NUMERIC,
  nullable. Live data shows the backfill APPLIED: all 6 users sit at `tp_pct=1.5000,
  sl_pct=0.5000` (4 balanced + 2 aggressive); **0 custom-TP/SL users** today.

## 5. Verdict

**CONDITIONAL PASS.**

Reasoning: #1688 is a net safety improvement — it removes the silently-ignored per-rule
TP/SL deception bug and a silent exception swallow, is well-tested (CI green at merge),
introduces no risk-constant / live-guard / threading / secret violation, and migration
089 is a clean reversible data-only backfill that is confirmed applied with sane data.
It is NOT a clean PASS: the one open item is **§3 — user-supplied TP/SL is consumed
with no server-side numeric bounds** (an unclamped capital-path input; e.g. `sl_pct=0`
or negative is not rejected). In production right now this is latent, not active: the
override is auth-gated and there are 0 custom-TP/SL users, all live values are sane
1.5/0.5. So no active capital risk, but a real input-validation gap.

Condition (recommend WARP🔹CMD open a follow-up lane):
- Add server-side bounds validation on `customTp` / `customSl` at the write path
  (`webtrader/backend/router.py`) and/or a clamp at the `_build_trade_signal` read site:
  reject `sl_pct <= 0`, reject negatives, cap `tp_pct` to a sane ceiling.
- Extend the NULL→default defensive fallback to the `fast_topup` / `safe_close` builder
  paths so a NULL row can never emit a position with `tp/sl = None`.

No blockers requiring rollback of #1688. Retroactive process note: this MAJOR lane
reached prod without a pre-merge SENTINEL gate (one of the §Process violations the
WARP-88 RCA should record); this report closes that gap retroactively.

---

Report path: `projects/polymarket/crusaderbot/docs/sentinel/1688_retroactive_sentinel.md`
Source PR: #1688 (sha `f6bdfd84`) · Source FORGE: `reports/forge/honest-tpsl-controls.md`
NEXT GATE: WARP🔹CMD — accept CONDITIONAL PASS + schedule the TP/SL-bounds follow-up lane.
