# WARP-75 — Auto-Trade Consent & Coverage Hardening (F1 + F3)

- **Role:** WARP•FORGE (scoped from WARP•R00T / WARP🔹CMD)
- **Branch:** `WARP/ROOT/auto-trade-consent-hardening`
- **Validation Tier:** STANDARD (escalate to MAJOR + SENTINEL only if F3 ever needs a capital-path change — it does not; F3 here is observability-only)
- **Claim Level:** NARROW INTEGRATION
- **Validation Target:** F1 — the two onboarding completion paths (`bot/handlers/start.py:skip_deposit_cb`, `bot/handlers/onboarding.py:_launch_cb`) must not enable `auto_trade_on` as a side effect. F3 — the autonomous scan loop (`services/signal_scan/signal_scan_job.run_once`) must never silently skip an opted-in user.
- **Not in Scope:** Live trading; the explicit user-initiated enable paths (Dashboard Auto-Mode toggle, preset activation, live CONFIRM) — all unchanged; any change to the 15-step gate or capital path.
- **Mode:** PAPER. `ENABLE_LIVE_TRADING` / `USE_REAL_CLOB` unchanged (False).

Derived from the WARP-69 audit findings, promoted by WARP🔹CMD:
- **F1 (consent integrity) = PAPER-public blocker.** A user must make a deliberate, explicit act to enable `auto_trade_on`; no side-effect activation from onboarding.
- **F3 (silent skip) = coverage/UX gap.** Silent skips with no log/page are wrong regardless of intent.

---

## 1. What was built

**F1 — onboarding never side-effect-enables autonomous trading.** Both onboarding completion handlers previously called `set_auto_trade(user_id, True)` on completion (including a fallback that fired even when no preset was chosen). Both calls are removed. Onboarding still applies the chosen preset *configuration* so the user is ready, but `auto_trade_on` stays at its default FALSE. Starting the loop now requires a deliberate explicit act — the Dashboard "🤖 Auto Mode" toggle (real capital additionally needs the typed-CONFIRM live activation gate, unchanged). The post-onboarding Dashboard renders Auto Mode OFF with that toggle as the explicit opt-in affordance.

**F3 — no silent skips of opted-in users.** Two previously silent paths in `run_once` now emit structured warnings:
- A non-NULL `active_preset` that maps to no strategy (deny-by-default: legacy/renamed/typo presets like `contrarian`, `full_auto`) → `scan_skipped_unmapped_preset` (previously fired nothing with no log; the existing `active_preset is NULL` path already logged `scan_skipped_no_preset`).
- A user who opted in (`auto_trade_on=TRUE`, not paused) but is missing the `signal_following` enrolment row the scan joins on → counted once per scan via `_count_optedin_unenrolled()` and surfaced as `scan_optedin_unenrolled` (the enrolment self-heals on the user's next `/start`).

Observability only — no capital-path change.

## 2. Current system architecture

```
ONBOARDING (start.skip_deposit_cb / onboarding._launch_cb)
  → upsert_user (auto_trade_on defaults FALSE; signal_following enrolled)
  → apply preset CONFIG (update_settings: active_preset, tp/sl, capital)   [no auto-enable]
  → set_onboarding_complete → Dashboard (Auto Mode OFF + explicit toggle)
                                                   │
                            user taps "🤖 Auto Mode" ON  ← the only enable path (explicit)
                                                   │
SCAN (signal_scan_job.run_once, every SIGNAL_SCAN_INTERVAL)
  → _load_enrolled_users() [auto_trade_on=TRUE ∧ signal_following ∧ not paused]
  → _count_optedin_unenrolled() → WARN scan_optedin_unenrolled if >0   (F3, fail-soft)
  → per user: if active_preset maps to no strategy → WARN scan_skipped_unmapped_preset, skip  (F3)
            else dispatch → 15-step gate → paper execution   (unchanged)
```

## 3. Files created / modified (full repo-root paths)

Modified (production):
- `projects/polymarket/crusaderbot/bot/handlers/start.py` — `skip_deposit_cb`: removed both `set_auto_trade(True)`/`set_paused(False)` side-effects (preset path + fallback); rewrote docstring/comments to the consent contract; dropped now-unused `set_auto_trade`/`set_paused` imports.
- `projects/polymarket/crusaderbot/bot/handlers/onboarding.py` — `_launch_cb`: removed the "Activate scanner" `set_auto_trade(True)`/`set_paused(False)` block; dropped now-unused imports.
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` — added `_count_optedin_unenrolled()` (fail-soft, returns -1 on any error incl. pool-not-ready); `run_once` emits `scan_optedin_unenrolled` (F3) and `scan_skipped_unmapped_preset` (F3).

Created:
- `projects/polymarket/crusaderbot/tests/test_auto_trade_consent_hardening.py` — 16 hermetic tests.
- `projects/polymarket/crusaderbot/reports/forge/auto-trade-consent-hardening.md` — this report.

Modified (state):
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- 16 new tests pass; `test_signal_scan_job.py` (full, 84) + my tests = 100 pass together; ruff + py_compile clean on all three modified production files.
- F1 proven: source-regression guards assert neither `skip_deposit_cb` nor `_launch_cb` calls `set_auto_trade`; behavioural test confirms `skip_deposit_cb` applies the preset config + completes onboarding with no enable path (the module no longer even imports `set_auto_trade`).
- F3 proven: `_count_optedin_unenrolled` returns the query count and is fail-soft (-1) on error; the unmapped-preset predicate is falsy for legacy/typo presets and truthy for all six shipping presets.
- In-lane bug caught + fixed: the first `_count_optedin_unenrolled` draft called `get_pool()` outside the try block, so a pool-not-ready `RuntimeError` escaped and broke `run_once` (the existing `run_once` tests caught it). `get_pool()` moved inside the try → truly fail-soft.

## 5. Known issues

- F2 (enrolment fail-soft, from the WARP-69 audit) is now *surfaced* by the `scan_optedin_unenrolled` coverage warning but the underlying enrolment is still written outside the `auto_trade_on` flip's transaction (`users.upsert_user`); it self-heals on the next `/start`. A transactional enrolment is an optional future hardening, not required here.
- Local test env lacks `fastapi`, so test files that transitively import the FastAPI app (e.g. `test_activation_handlers.py`) fail at import locally; they pass in CI. Unrelated to this lane.

## 6. What is next

- WARP🔹CMD review of this PR. **HOLD merge** until the WARP-72 data-window checkpoint (every merge → Fly CD redeploy resets the RTDS oracle buffer + clears in-flight paper positions).
- After WARP-75 closes → Lane 2 (WARP-74 staging crash-sim proof) prep begins, per the directive.
- No SENTINEL run required (STANDARD; F3 observability-only, F1 tightens consent without a capital-path change).

---

**Suggested Next Step:** WARP🔹CMD reviews + holds for the data window; on close, proceed to WARP-74 staging-proof prep.
