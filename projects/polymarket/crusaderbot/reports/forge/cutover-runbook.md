# WARP-78 Cutover Track B — orchestrator kill-switch + cutover runbook

- Role: WARP•R00T
- Validation Tier: MAJOR (the cutover safety kill-switch — a runtime gate on the
  execution selection path), though **dormant + default-OFF + additive** (no
  caller yet; changes zero current behavior). Merged under WARP•R00T authority;
  hermetic tests stand in for the SENTINEL gate.
- Claim Level: NARROW INTEGRATION (kill-switch wired into runtime_config + config
  + ev_comparator with hermetic tests; the orchestrator routing it gates is NOT
  yet built — that is the future cutover PR).
- Validation Target: an instant, no-redeploy emergency fallback that forces
  `candle_auto`+`auto` users from the EV-comparator orchestrator back to the
  precedence router, plus the operator runbook for the code-level cutover.
- Not in Scope: the cutover routing wire itself (`candle_auto`+`auto` →
  `EVComparator.select` in late_entry_v3 — the future PR); generating the real
  `config/ev_comparator_model.json`; flipping anything in prod.
- Branch: `WARP/cutover-runbook`

---

## 1. What was built

The emergency kill-switch for the WARP-78 cutover (corrected architecture:
code-level cutover + runtime_config kill-switch, NOT a Fly-secret flag), plus
the operator runbook.

- **`domain/ops/runtime_config.py`** — added `ORCHESTRATOR_KILL_SWITCH`
  `SettingSpec(bool)` to `RUNTIME_SETTINGS`, **mirroring the
  `SCAN_SNAPSHOT_ENABLED` pattern (#1663)** exactly (same whitelist, `resolve_bool`,
  `system_settings cfg:` overlay, 30 s cache, fail-safe to env default).
- **`config.py`** — `ORCHESTRATOR_KILL_SWITCH: bool = False` static backstop (set
  `true` as a Fly secret for a redeploy-proof hard halt that survives a DB outage).
- **`domain/strategy/ev_comparator.py`** — two async gate helpers:
  - `orchestrator_kill_switch_active()` — reads the overlay (DB → env/Fly → code
    default False), fail-soft.
  - `orchestrator_routes(preset, rule)` — `True` iff `preset == "candle_auto"` AND
    `rule == "auto"` AND the kill-switch is OFF; else the router. This is the
    single gate the future cutover wire calls.
  - Constants `CANDLE_AUTO_PRESET="candle_auto"`, `ORCHESTRATOR_RULE="auto"`;
    both helpers + constants exported in `__all__`.
- **`docs/runbooks/orchestrator-cutover.md`** — the runbook: pre-cutover
  checklist, cutover sequence (PR merge + Fly CD), 30-min verification (incl.
  pinned-rule leak check + per-cell sanity), instant kill-switch rollback (exact
  admin endpoint + SQL fallback), hard rollback (Fly-secret backstop / PR revert),
  and an internal comms template.

### Dormancy (zero behavior change today)
Nothing calls `orchestrator_routes` yet — the `candle_auto`+`auto` →
`EVComparator.select` routing wire lands with the cutover PR. The kill-switch is
default OFF, additive, and fail-soft; current prod behavior is unchanged. When
the cutover wire ships, it consults this gate, so the kill-switch is ready before
the behavior it protects exists.

## 2. Current system architecture

```
candle_auto + rule="auto"  ──► orchestrator_routes(preset, rule)
                                    │
                  ┌─────────────────┴───────────────────┐
                  │ kill-switch OFF                       │ kill-switch ON
                  ▼                                       ▼  (or non-auto / other preset)
        EVComparator.select  (future cutover wire)   precedence router (unchanged)

orchestrator_kill_switch_active():
    runtime_config.resolve_bool("ORCHESTRATOR_KILL_SWITCH",
                                env_default = Settings.ORCHESTRATOR_KILL_SWITCH)
    precedence: system_settings cfg: override → env/Fly → code default False
    (30 s cache; admin PATCH/DELETE /admin/settings/{key} invalidates on write)
```

## 3. Files created / modified (full repo-root paths)

- Modified: `projects/polymarket/crusaderbot/domain/ops/runtime_config.py`
- Modified: `projects/polymarket/crusaderbot/config.py`
- Modified: `projects/polymarket/crusaderbot/domain/strategy/ev_comparator.py`
- Created: `projects/polymarket/crusaderbot/docs/runbooks/orchestrator-cutover.md`
- Created: `projects/polymarket/crusaderbot/tests/test_warp78_orchestrator_kill_switch.py`
- Created: `projects/polymarket/crusaderbot/reports/forge/cutover-runbook.md`
- State sync: `state/PROJECT_STATE.md`, `state/CHANGELOG.md`

## 4. What is working

- `tests/test_warp78_orchestrator_kill_switch.py` — 9 hermetic tests (fake
  asyncpg pool, mirrors `test_runtime_config.py`): whitelist/type, default-OFF →
  orchestrator allowed, override-ON → router, override-OFF keeps orchestrator,
  env/Fly backstop engages without a DB row, DB-OFF beats env-ON, gate is
  `candle_auto`+`auto`-only (pinned rule + other presets + `None` → router),
  persistence across reads, set/clear override round-trip.
- Full `test_runtime_config.py` (19 tests) still passes — no regression to the
  existing whitelist. Combined run: **28 passed**. `ruff` clean.
- Kill-switch toggle is a no-redeploy DB write (admin PATCH / SQL); propagation
  ≤30 s (cache TTL) for the worker, immediate in the writing process.

## 5. Known issues

- The orchestrator **routing wire is not built here** — `orchestrator_routes`
  has no caller yet. The cutover PR adds the `candle_auto`+`auto` →
  `EVComparator.select` call in late_entry_v3 and is gated on Track C PASS. Until
  then the kill-switch is dormant (it protects behavior that does not yet exist).
- No `config/ev_comparator_model.json` exists yet — the cutover PR must also
  generate + commit the real model, or the comparator abstains into zero trades
  (called out in the runbook pre-cutover checklist).
- Fail-safe direction mirrors `SCAN_SNAPSHOT_ENABLED` (error → env default). A
  sustained DB outage with the operator's DB kill-switch set ON would revert to
  the env default; the runbook §5 Fly-secret backstop covers that case.

## 6. What is next

- WARP🔹CMD: review + merge. After Track C sign-off + real-data Track D PASS,
  author the **cutover PR** (routing wire + committed model) and follow
  `docs/runbooks/orchestrator-cutover.md`.
- This completes the 4-track WARP-79 readiness set (A pipeline dry-run, C
  criteria, D report template, B kill-switch + runbook).

Suggested Next Step: WARP🔹CMD review + merge the kill-switch; it must be in prod
BEFORE the cutover PR so the fallback exists the moment the orchestrator routes.
