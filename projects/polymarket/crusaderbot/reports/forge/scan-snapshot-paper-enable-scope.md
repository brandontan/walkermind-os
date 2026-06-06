# Scope — SCAN_SNAPSHOT_ENABLED paper-enable lane

Role: WARP•R00T (scope/plan only — NO code change, NO flip in this lane)
Validation Tier: STANDARD (the eventual enable lane; this scope doc itself is MINOR)
Claim Level: FOUNDATION (scope only — nothing built/enabled)
Validation Target: define an accurate, low-risk path to begin `market_snapshots`
accrual in PAPER so the late_entry_v3 OOS proof (WARP-58) + walk-forward replay
(Lane 2c-3) have a bias-free historical substrate.
Not in Scope: actually flipping the flag; any code change; live trading; retention
automation; the OOS→risk-gate wiring (WARP-55).
Suggested Next Step: WARP🔹CMD picks Path A or Path B below, then opens the
implementation lane on a fresh `WARP/`/`warp/` branch.

---

## 1. Objective

`market_snapshots` is empty because `SCAN_SNAPSHOT_ENABLED` defaults OFF. Until it
accrues real PAPER scan history, `late_entry_v3` OOS edge stays UNPROVEN and the
replay engine returns `{}`. This lane scopes the safest way to start that accrual.

## 2. Current mechanism (verified in code)

- `config.py:156` — `SCAN_SNAPSHOT_ENABLED: bool = False` (static pydantic setting;
  sourced from env/Fly only).
- `services/signal_scan/signal_scan_job.py:3085-3093` — the capture hook reads the
  flag via `getattr(_get_settings(), "SCAN_SNAPSHOT_ENABLED", False)` (fail-soft to
  False), then `await record_market_snapshots(run_id, markets)`. Captured from the
  raw full Gamma universe BEFORE any strategy filtering → no selection bias.
- `domain/research/snapshots.py` — `record_market_snapshots`: append-only, fail-soft
  (any write error logs + returns 0; never breaks the scan loop). Stores
  best_bid/ask/mid/liquidity + full `raw` JSONB.
- `migrations/080_market_snapshots.sql` — table + 3 indexes + RLS deny-by-default
  (service role writes, no anon/auth access). Handoff states the table EXISTS but is
  empty → mig 080 already applied (confirm before enabling — see §6).
- `domain/research/late_entry_oos.py` — `run_oos()` (line 311); `MIN_OOS_TRADES = 20`
  (line 67); status `MEASURED` only when `n >= MIN_OOS_TRADES`, else `UNPROVEN_THIN`.
  Runnable as a module (`__main__`, line 383).

## 3. Decisive finding — NOT runtime-toggleable today

Unlike WEATHER / COMPLETE_SET_ARB / PLAYBOOK (which read through
`domain/ops/runtime_config.py` `resolve_bool()` and ARE in the `RUNTIME_SETTINGS`
whitelist, `runtime_config.py:61-80`), the snapshot gate reads STATIC settings
directly. Consequences:

- It CANNOT be flipped from the web admin (runtime-config-admin #1565) — the key is
  not whitelisted and the read site never consults the DB overlay.
- Enabling it today requires setting the env var `SCAN_SNAPSHOT_ENABLED=true` in Fly
  + redeploy → **the same flyctl/CD blocker as the #1595/#1596 redeploy** (flyctl
  unavailable in the cloud agent env; operator action).

This corrects the handoff assumption that the flip is "the one real-data action in
agent reach" — as wired today it is an operator/redeploy action, not in agent reach.

## 4. Two enable paths

### Path A — env flag + Fly redeploy (no code change)
- Operator sets Fly env `SCAN_SNAPSHOT_ENABLED=true` and redeploys.
- Pros: zero code; minimal surface. Cons: needs flyctl/CD (operator); not toggleable
  at runtime; bundle with the pending #1595/#1596 redeploy to amortize one deploy.

### Path B — wire into runtime_config, then DB toggle (RECOMMENDED)
- Small STANDARD code lane:
  1. Add `SCAN_SNAPSHOT_ENABLED` `SettingSpec(kind="bool")` to `RUNTIME_SETTINGS`
     (`runtime_config.py:61`).
  2. Convert the read site (`signal_scan_job.py:3086`) from `getattr(_get_settings()…)`
     to `await _runtime_config.resolve_bool("SCAN_SNAPSHOT_ENABLED", <env_default>)`
     — mirrors the PLAYBOOK pattern at `signal_scan_job.py:3117`.
  3. Add a focused test (overlay ON → capture invoked; OFF/error → fail-safe skip).
- After this one-time wiring lands + deploys, the operator (or an authorized agent
  via the admin/DB) can flip it ON/OFF in PAPER without any further redeploy — this
  is what actually puts the flip "in reach."
- Pros: matches the established strategy-flag pattern; fail-safe precedence (code →
  env → DB); future ON/OFF needs no deploy. Cons: one deploy to land the wiring.

## 5. Risk / safety analysis

- Trading impact: NONE. Capture is append-only telemetry on the raw universe; it
  does not touch DATA→…→EXECUTION, risk constants, Kelly, or the LIVE guard.
- Failure isolation: recorder is fail-soft (errors log + return 0); the settings read
  is wrapped in try/except → a misconfig can never break the scan loop.
- Data safety: RLS deny-by-default; no user-identifiable data; service-role writes
  only. No FK into trading tables.
- Inviolable invariants: untouched — no secrets, asyncio only, no `phase*/`, no
  Kelly change, `ENABLE_LIVE_TRADING` not in this path.

## 6. Prerequisites (verify before enabling)
- Confirm mig 080 applied on Supabase prod (`market_snapshots` exists) — read-only
  `list_migrations` / `list_tables`. Handoff implies it exists (empty), but confirm.
- Confirm the scan loop runs in PAPER on the deployed bot (it does — scan job is the
  capture call site).

## 7. Acceptance criteria (for the eventual enable lane)
- After enable: `market_snapshots` row count grows each scan tick; `scan_runs`
  `snapshots_written > 0`.
- Accrue across real candle cycles until a preset reaches `n >= MIN_OOS_TRADES` (20).
- Re-run `domain/research/late_entry_oos.py` → per-preset status flips from
  `UNPROVEN_THIN`/`UNPROVEN_NO_DATA` to `MEASURED` with a realized `edge_bps`.
- Retention: operator prunes per the horizon noted in mig 080 (e.g. 90 days).

## 8. Recommendation

Path B (runtime_config wiring) as a small STANDARD lane, so the PAPER flip becomes a
no-redeploy DB toggle going forward. If the team wants accrual started immediately
and a deploy is already happening for #1595/#1596, piggyback Path A on that same
redeploy and still do Path B afterward for ongoing control.
