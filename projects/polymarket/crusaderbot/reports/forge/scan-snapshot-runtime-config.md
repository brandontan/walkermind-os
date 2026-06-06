# WARP-58 side lane — SCAN_SNAPSHOT_ENABLED runtime-config wire

Role: WARP•R00T (build)
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: `SCAN_SNAPSHOT_ENABLED` resolution path — convert the
`market_snapshots` capture gate from a static (Fly/env) setting to a
runtime_config DB overlay so the PAPER flip becomes a no-redeploy operator
toggle. Default stays OFF (no behavior change in prod until the operator flips it).
Not in Scope: actually flipping the flag ON; any change to the recorder
(`record_market_snapshots`), the OOS engine, the replay engine, WARP-78 strategy
code, WARP-77 plumbing, or any prod runtime path beyond this one gate.
Suggested Next Step: WARP🔹CMD greenlight → operator flips the toggle in PAPER
(web admin or DB) → `market_snapshots` begins accruing → re-run
`domain/research/late_entry_oos.py` once a preset reaches `MIN_OOS_TRADES=20`.

---

## 1. What was built

The Path B recommendation from `reports/forge/scan-snapshot-paper-enable-scope.md`:
`SCAN_SNAPSHOT_ENABLED` is now wired into the runtime_config overlay
(`domain/ops/runtime_config.py`), so it can be flipped ON/OFF in PAPER from the
web admin or DB **without a redeploy**. Previously the gate read STATIC pydantic
settings directly, so enabling it required setting a Fly env var + redeploy
(the same flyctl/CD blocker that holds up #1595/#1596).

Resolution precedence (unchanged pattern, mirrors WEATHER / PLAYBOOK / COMPLETE_SET_ARB):
**code default → env/Fly (`config.Settings`) → DB override** (DB wins, whitelisted
keys only). Reads fail SAFE — any DB error falls back to the static env default,
which is OFF for this flag.

No migration is required: runtime_config is a sparse overlay on the existing
`system_settings` table (`cfg:` namespace). "Default false" = absence of an
override row → env default (`SCAN_SNAPSHOT_ENABLED: bool = False`). A row is
created on-demand only when the operator sets the toggle.

## 2. Current system architecture

```
scan tick (signal_scan_job.run_once)
  └─ fetch raw full-universe markets (BEFORE strategy filtering → no selection bias)
       └─ _snap_enabled = runtime_config.resolve_bool(
              "SCAN_SNAPSHOT_ENABLED",
              env_default = settings.SCAN_SNAPSHOT_ENABLED)   # try/except → False on error
            (precedence: code → env/Fly → DB overlay; fail-safe to env default)
          if _snap_enabled:
              tel.snapshots_written += await record_market_snapshots(run_id, markets)
                                          (append-only, fail-soft — never breaks the loop)

operator toggle (no redeploy):
  web admin  → PATCH /admin/settings/SCAN_SNAPSHOT_ENABLED {"value": true}
             → runtime_config.set_override (validated, audited, cache-invalidated)
  or DB      → INSERT system_settings (key='cfg:SCAN_SNAPSHOT_ENABLED', value='true')
  effective within CACHE_TTL_SECONDS (30s) across processes; immediate in writer process
```

The admin surface is generic over `RUNTIME_SETTINGS` — adding the whitelist entry
auto-exposes the toggle through the existing endpoints (`GET/PATCH/DELETE
/admin/settings`, `webtrader/backend/router.py`); no new endpoint was needed.

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/domain/ops/runtime_config.py` — added
  `SCAN_SNAPSHOT_ENABLED` `SettingSpec(kind="bool")` to the `RUNTIME_SETTINGS`
  whitelist.
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` —
  converted the capture-gate read (~line 3085) from
  `getattr(_get_settings(), "SCAN_SNAPSHOT_ENABLED", False)` to
  `await _runtime_config.resolve_bool("SCAN_SNAPSHOT_ENABLED", <env_default>)`,
  keeping the surrounding try/except → False fail-safe. Mirrors the PLAYBOOK gate
  in the same function.
- `projects/polymarket/crusaderbot/config.py` — doc-comment on the static
  `SCAN_SNAPSHOT_ENABLED` setting now notes it is runtime-config wired (DB overlay
  overrides; no-redeploy PAPER flip).
- `projects/polymarket/crusaderbot/tests/test_runtime_config.py` — added 5 focused
  tests (whitelist presence + bool kind; dormant-by-default; DB override enables;
  override OFF beats env ON; appears in `list_effective`) and added
  `SCAN_SNAPSHOT_ENABLED` to the `_Settings` stub.
- `projects/polymarket/crusaderbot/reports/forge/scan-snapshot-runtime-config.md` —
  this report.
- State sync: `state/PROJECT_STATE.md`, `state/CHANGELOG.md`, `state/WORKTODO.md`.

## 4. What is working

- `python -m pytest projects/polymarket/crusaderbot/tests/test_runtime_config.py -q`
  → **19 passed** (14 prior + 5 new).
- AST parse clean on all 3 modified modules (`runtime_config.py`,
  `signal_scan_job.py`, `config.py`).
- Default-OFF preserved: with no override row, `resolve_bool` returns the env
  default (`False`) → capture stays dormant in prod until the operator flips it.
- Fail-safe precedence reused verbatim from the proven WEATHER/PLAYBOOK pattern:
  DB error / unparseable value → env default; the gate read is additionally
  wrapped in try/except → False.
- Kill-switch precedence holds: a DB `false` override beats an env `true`
  (`test_scan_snapshot_override_off_beats_env_on`).

## 5. Known issues

- The capture branch in `run_once` is exercised end-to-end only in PAPER on the
  deployed bot (no hermetic `run_once` snapshot harness exists in
  `test_signal_scan_job.py`); the resolution logic itself is fully unit-covered.
  Operator-runbook verification is included below per the scope's acceptance.
- Migration 080 (`market_snapshots`) is assumed applied (handoff says the table
  exists but is empty). Confirm via `list_tables` before flipping (read-only).
- This lane does NOT start accrual — it only makes the flip a no-redeploy toggle.
  The flip itself awaits WARP🔹CMD greenlight (default OFF until then).

## 6. What is next

1. WARP🔹CMD greenlight to flip `SCAN_SNAPSHOT_ENABLED` ON in PAPER.
2. Operator toggle (no redeploy):
   - Web admin: `PATCH /admin/settings/SCAN_SNAPSHOT_ENABLED` body `{"value": true}`.
   - Or DB: `INSERT INTO system_settings (key, value, updated_at)
     VALUES ('cfg:SCAN_SNAPSHOT_ENABLED', 'true', NOW())
     ON CONFLICT (key) DO UPDATE SET value='true', updated_at=NOW();`
   - Revert: `DELETE /admin/settings/SCAN_SNAPSHOT_ENABLED` (reverts to env default OFF).
3. Verify accrual: `market_snapshots` row count grows each scan tick;
   `scan_runs.snapshots_written > 0`.
4. Accrue across real candle cycles until a preset reaches `n >= MIN_OOS_TRADES` (20).
5. Re-run `domain/research/late_entry_oos.py` → per-preset status flips from
   `UNPROVEN_THIN` / `UNPROVEN_NO_DATA` to `MEASURED` with a realized `edge_bps`
   (unblocks the WARP-58 OOS proof + Lane 2c-3 walk-forward replay).

## 7. Safety / invariants

- Trading impact: NONE. Capture is append-only telemetry on the raw universe; it
  does not touch DATA→…→EXECUTION, risk constants, Kelly, or the LIVE guard.
- Inviolable invariants untouched: no secrets, asyncio only, no `phase*/`, no Kelly
  change, `ENABLE_LIVE_TRADING` not in this path. The runtime_config whitelist is
  structurally barred from shadowing secrets / LIVE guards
  (`test_whitelist_excludes_secrets_and_guards` still passes).
- Default state OFF → zero behavior change in prod until the operator toggles.

Validation Handoff (NEXT PRIORITY):

```
WARP🔹CMD review required.
Source: projects/polymarket/crusaderbot/reports/forge/scan-snapshot-runtime-config.md
Tier: STANDARD
```
