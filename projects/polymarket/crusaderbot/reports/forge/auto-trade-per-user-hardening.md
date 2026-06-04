# WARP-69 — Per-User Autonomous Auto-Trade Loop: Hardening & Audit

- **Role:** WARP•FORGE (scoped from WARP•R00T directive)
- **Branch:** `WARP/ROOT/auto-trade-per-user`
- **Validation Tier:** STANDARD
- **Claim Level:** NARROW INTEGRATION (audit + invariant tests on the existing runtime; no production-logic change)
- **Validation Target:** The existing per-user autonomous auto-trade loop — `services/signal_scan/signal_scan_job.run_once` → existing selection path → 15-step risk gate (`domain/risk/gate.evaluate`) → paper execution (`domain/execution/paper.execute`), gated per-user by `users.auto_trade_on`.
- **Not in Scope:** Live trading; the WARP-72 scorer / orchestrator; sizing-by-conviction; any change to onboarding consent flow or the `signal_following` enrollment coupling (both surfaced below as findings, scoped separately per WARP🔹CMD); fixing the two reported findings in-lane.
- **Mode:** PAPER. `ENABLE_LIVE_TRADING` unchanged (False). `USE_REAL_CLOB` unchanged (False).

---

## 1. What was built

WARP🔹CMD confirmed (Option 1) that a per-user autonomous auto-trade loop **already exists and runs in paper** — `auto_trade_on` is the single canonical opt-in and no parallel `AUTO_TRADE_ENABLED` flag/gate is to be added (a duplicate capital-path gate is the forbidden pattern). This lane therefore delivers an **audit with code-cited evidence** against CMD's 5-item checklist plus a **focused hermetic test file** that pins the three safety invariants so a future refactor cannot silently regress them. No production code was modified.

Audit verdict: **no real capital-path defect → lane stays STANDARD.** Two reportable findings (both paper-only / benign) are documented for separate scoping.

## 2. Current system architecture

The autonomous loop (unchanged, validated):

```
scheduler (signal_scan, every SIGNAL_SCAN_INTERVAL)
  → signal_scan_job.run_once()                              [signal_scan_job.py:2950]
      → _load_enrolled_users()                              [signal_scan_job.py:652]
          WHERE us.strategy_name='signal_following'
            AND us.enabled=TRUE
            AND u.auto_trade_on=TRUE                         ← canonical per-user opt-in
            AND u.paused=FALSE
            AND NOT EXISTS(strategies.enabled=FALSE)         ← global operator off-switch
      → per user: dispatch active_preset via _preset_allows  [Phase-B candle/weather/playbook/complete-set]
      → _process_candidate → _engine.execute
          → gate.evaluate(GateContext)                       [gate.py:321] — 15 steps, fail-first
          → paper.execute(...)                               [paper.py] — user_id-scoped, ON CONFLICT dedup
```

Audit findings (file:fn:line · PASS/DEFECT):

1. **Per-user isolation — PASS.** Every per-user query in the path is `WHERE user_id=$1`: `gate._open_position_count` (gate.py:124), `_open_exposure` (137), `_max_drawdown_breached` ledger+wallets (151/157), `_recent_dup_market_trade` (193), `_record_idempotency` (182); `_publication_already_queued` (signal_scan_job.py:1017) backed by `execution_queue UNIQUE(user_id, publication_id)`. The one global-keyed lookup `gate._idempotent_already_seen` (gate.py:172, `WHERE key=$1`) is per-user safe because `_build_idempotency_key` (signal_scan_job.py:1731) folds `user_id` into the SHA-256 — distinct users on the same market/side/day produce distinct keys. `paper.execute` scopes orders/positions/ledger/wallet by user_id.

2. **Gate-respect — PASS.** The loop's only entry path is `_process_candidate → _engine.execute → gate.evaluate` (full 15 steps). `validate_risk_caps` (gate.py:253) enforces hard ceilings (balance>0 / ≤`MAX_SINGLE_POSITION_PCT` / open-count cap). User-owned risk can only **tighten**: drawdown `min(8% floor, user_pct)` and only when `0 < user_pct < threshold` (gate.py:163); Kelly clamped ≤0.25; daily-loss/exposure use most-restrictive selection. Kill switch (step 1, gate.py:342) and live guards (`_passes_live_guards`, gate.py:201) are un-bypassable from user settings.

3. **Consent integrity — FINDING (paper-only).** Default FALSE (migration 001; `services/user_service.py:24`). LIVE enable requires a typed **CONFIRM** + full `live_checklist.evaluate` (`bot/handlers/activation.py:106-153`) → real-capital consent is solid. **However** onboarding `skip_deposit_cb` (`bot/handlers/start.py:234` + fallback 246-249) flips `auto_trade_on=True` on completion **even when no preset was chosen** (the documented MVP #1089 "never strand the user" P0 fix). That auto-enables autonomous **paper** trading without an explicit trade-consent tap, which conflicts with the directive's strict "explicit opt-in." No real capital is ever at risk (live still needs CONFIRM). See §5.

4. **Documentation — PASS.** `auto_trade_on` already noted canonical at `bot/handlers/mvp/dashboard.py:31` ("NOT auto_trade_enabled"). `AUTO_TRADE_ENABLED` was never introduced and is explicitly dropped.

5. **Coupling — PASS + observation.** `_enroll_signal_following` (`users.py:16`) is called by `upsert_user` (`users.py:99`) on every `/start`, idempotent (`ON CONFLICT DO NOTHING`) → every onboarded user has the `signal_following` `user_strategies` row the enrollment query requires; **no silent-skip** under normal flow. See §5 for two carry-forward notes.

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/tests/test_auto_trade_per_user_hardening.py` — 12 hermetic tests (dedup-key per-user isolation ×4; drawdown tighten-only ×4; gate consent/pause/kill-switch enforcement ×4).
- `projects/polymarket/crusaderbot/reports/forge/auto-trade-per-user-hardening.md` — this report.

Modified (state only):
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

Production code modified: **none.**

## 4. What is working

- 12/12 new tests pass (`pytest`); ruff clean.
- Proven invariants: (a) the dedup key embeds `user_id`, so the gate's global-keyed dedup cannot cross-contaminate users; (b) a user-set drawdown threshold above 8% cannot prevent the 8% halt, and a stricter value halts earlier; (c) `gate.evaluate` rejects autonomous entries when `auto_trade_on=False` (step 2), when `paused=True` (step 2), and when the kill switch is active (step 1), before any sizing/execution.
- Real-capital consent confirmed gated behind typed CONFIRM + live checklist.
- `signal_following` enrollment confirmed universal + idempotent → opted-in users are not silently skipped.

## 5. Known issues / findings (paper-only; scope separately per WARP🔹CMD)

- **F1 — Consent fallback auto-enables paper autonomy.** `bot/handlers/start.py` onboarding (`skip_deposit_cb`, lines 234 + 246-249) sets `auto_trade_on=True` on completion even with no preset chosen. Paper-only (live remains CONFIRM-gated). Recommendation: WARP🔹CMD decides whether to require an explicit post-onboarding "Start auto-trade" tap. Not changed in-lane (alters the onboarding funnel — out of scope).
- **F2 — Enrollment is fail-soft.** `_enroll_signal_following` is wrapped in a logged try/except (`users.py:100`); a transient INSERT failure at the moment `auto_trade_on` flips would skip the user from scans until the next `/start` self-heals. Low impact (idempotent self-heal). Optional follow-up: enroll inside the same transaction that flips `auto_trade_on`.
- **F3 — Implicit coupling.** Gating the candle/weather/playbook autonomous dispatch on a `signal_following` `user_strategies` row is a benign historical artifact (enrollment is universal) but is implicit. Recommendation: document `signal_following` enrollment as the canonical autonomous-enrollment marker, or decouple the load to `auto_trade_on` alone. Not a capital-path defect.

## 6. What is next

- WARP🔹CMD review of this report + PR. **HOLD merge** until the WARP-72 data-window checkpoint (every merge → Fly CD redeploy resets the RTDS oracle buffer + clears in-flight paper positions).
- WARP🔹CMD decision on F1 (explicit post-onboarding opt-in tap) and F3 (decouple vs document the `signal_following` coupling) — each its own lane if pursued.
- No SENTINEL run required (STANDARD; no capital-path defect). Reclassify to MAJOR + SENTINEL only if F1/F3 are pursued as runtime changes.

---

**Suggested Next Step:** WARP🔹CMD reviews the audit + holds the PR for the data-window checkpoint; decide F1/F3 disposition as separate lanes.
