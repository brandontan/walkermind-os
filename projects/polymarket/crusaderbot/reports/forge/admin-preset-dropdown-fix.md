# WARP — /admin user-detail preset dropdown fix

Role: WARP•R00T (build)
Validation Tier: STANDARD (operator-facing admin UI; no trading/runtime/risk surface)
Claim Level: NARROW INTEGRATION
Validation Target: the /admin user-detail "Active preset" dropdown
(AdminUserDrawer.tsx) now offers every canonical, activatable preset — adding the
two CMD found missing: `candle_auto` (Smart Strike) and `playbook`.
Not in Scope: creating a new `smart_strike` preset key (see §2); renaming the
`weather_monitor` key (see §2); the user-facing AutoTradePage picker (already
complete via /autotrade/preset-availability); enabling/relaxing weather/playbook
entry thresholds (separate lane — see reports/forge/weather-playbook-entry-gate-investigation.md).
Suggested Next Step: WARP🔹CMD review + merge; optional follow-up = weather/playbook
edge-tuning lane from the #1664 investigation.

---

## 1. What was built

The operator's /admin user-detail drawer had a **hardcoded, stale** preset list:

```ts
// AdminUserDrawer.tsx (before)
const PRESETS = ["close_sweep", "safe_close", "flip_hunter", "weather_monitor"];
```

This is the only place the two presets were missing. Fix:

- `PRESET_OPTIONS` now mirrors the canonical `domain/preset/presets.py`
  `PRESET_ORDER` exactly (6 presets), with `{value, label}` options so the
  persisted key stays visible to the operator alongside a human name:
  `candle_auto`, `close_sweep`, `safe_close`, `flip_hunter`, `weather_monitor`,
  `playbook`.
- `FieldSelect` extended to accept `string | {value,label}` options
  (backward-compatible — the other selects pass plain string arrays unchanged).
- `CRYPTO_SHORT_PRESETS` (frontend) now includes `candle_auto`, matching the
  backend `_CRYPTO_SHORT_PRESETS` (router.py), so picking Smart Strike reveals the
  timeframe/asset fields like the other candle presets.

No backend code change was needed — the backend was **already fully wired** for
both keys (see §3).

## 2. Naming decisions (R00T call — CMD delegated naming)

**`smart_strike` → use the existing `candle_auto` key.** The canonical preset for
"the bot scores 7 factors and picks the best of close_sweep/safe_close/flip_hunter"
already exists as `candle_auto` (display name **"Smart Strike"** in presets.py),
is fully wired, and has a live user (`active_preset='candle_auto'` in prod). It is
exactly the EV-comparator entry point that engages when `ORCHESTRATOR_ACTIVE`
flips at the Phase-4 cutover. Creating a separate `smart_strike` key would
duplicate `_PRESET_TO_STRATEGY`/`_PRESET_PARAMS`, fragment persisted
`active_preset` values, and require a later DB migration. So the dropdown exposes
`candle_auto` with the label "Smart Strike (auto: scores 7 factors, picks
close/safe/flip)". No new key created.

**`weather_monitor` → key kept; label only.** Renaming the key to `weather`
would orphan 2 live users (`active_preset='weather_monitor'`) and every backend
map (`_PRESET_TO_STRATEGY`, `_PRESET_LOCKED_CATEGORY`, `_PRESET_ALLOWED`,
presets.py) + the DB column — high risk, low value. The dropdown label keeps the
key visible; the human name is "Weather Monitor". If CMD still wants the key
aligned to `weather`, that is a separate migration lane.

## 3. Backend was already wired (verification)

`webtrader/backend/router.py` already contained both keys in every relevant map:

- `_PRESET_TO_STRATEGY` (1065-1072): `candle_auto→late_entry_v3`, `playbook→playbook`
- `_PRESET_PARAMS` (1122-1134): activation defaults for both
- `_PRESET_LOCKED_CATEGORY` (1144-1151): `candle_auto→Crypto`, `playbook→Sports`
- `_CRYPTO_SHORT_PRESETS` (1138): `candle_auto`
- admin-patch validator (3191): validates `active_preset ∈ _PRESET_TO_STRATEGY`
  → already accepts both. `presets.py` lists both in `VISIBLE_PRESET_ORDER` and
  `HIDDEN_PRESETS` is empty → both `is_activatable`.

So an operator selecting either preset would have persisted + scanned correctly —
the dropdown was the sole gap. The user-facing picker
(`/autotrade/preset-availability`, iterates `_PRESET_TO_STRATEGY`) already shows
all six; only the admin drawer hardcoded a subset.

## 4. Item 3 — scan_snapshot toggle is NOT redundant with WARP/scan-snapshot-runtime-config

CMD asked whether the existing runtime_config dashboard toggle already implements
what `WARP/scan-snapshot-runtime-config` (#1663, MERGED) did. **Answer: NO — that
branch IS the implementation, not a duplicate.** Before #1663:

- `SCAN_SNAPSHOT_ENABLED` was **not** in `runtime_config.RUNTIME_SETTINGS`, and
  the read site in `signal_scan_job` read STATIC settings
  (`getattr(_get_settings(), ...)`), never the DB overlay. The generic admin
  toggle (`PATCH /admin/settings/{key}`) only honours whitelisted keys, so it had
  **no effect** on snapshot capture.
- #1663 added the whitelist entry + converted the read site to
  `resolve_bool(...)`. The operator's live `cfg:SCAN_SNAPSHOT_ENABLED=true` row
  (set 14:07 UTC) works **because of** #1663 — `markets`/snapshot capture is now
  active. Keep #1663 (already merged); nothing to close as redundant.

## 5. Item "ALSO" — why weather/playbook still show 0 entries (cross-ref #1664)

Already diagnosed in `reports/forge/weather-playbook-entry-gate-investigation.md`
(PR #1664, MERGED). Summary for this CMD note: it is **not** a 30s toggle
propagation lag and **not** a toggle→scan-loop wiring gap. `scan_runs.
zero_reason_breakdown` shows `weather:filter_or_no_match` + `playbook:filter_or_no_match`
(NOT `strategy_disabled`) every tick → flags are ON, strategies dispatch + run
`.scan()`, and return zero candidates. The 30s `runtime_config` CACHE_TTL is real
but irrelevant: the flags have been ON and stable, and markets sync fresh every
tick (14:10 UTC). Root cause = opportunistic edge starvation (weather needs a
≥10%-EV ≤0.45-price daily-city dislocation + live forecast; playbook needs an
in-window sports market + a router module edge, with 2 of 4 alpha modules dark on
the default NullFeed). The fix path (observability / threshold tuning / playbook
feeds) is CMD's call — see §6 of that report.

## 6. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/AdminUserDrawer.tsx`
  — `PRESET_OPTIONS` (canonical 6 presets, labeled), `FieldSelect` labeled-option
  support, `CRYPTO_SHORT_PRESETS` includes `candle_auto`.
- `projects/polymarket/crusaderbot/tests/test_admin_console.py` — +3 tests pinning
  the admin preset contract (candle_auto + playbook accepted; dropdown == canonical
  registry; bogus key still rejected).
- Frontend e2e (Playwright) — NEW:
  - `webtrader/frontend/e2e/run-preset-dropdown.mjs` — Playwright-as-a-library
    driver (boots Vite dev, drives real Chromium against the harness, asserts the
    option contract, writes the before/after screenshot).
  - `webtrader/frontend/preset-demo.html` + `webtrader/frontend/src/devtools/presetDemo.tsx`
    — dev/e2e harness rendering the REAL FieldSelect + PRESET_OPTIONS (no mocks; not
    wired into the app router).
  - `webtrader/frontend/playwright/__screenshots__/preset-dropdown-before-after.png`
    — the before/after dropdown screenshot.
  - `webtrader/frontend/package.json` — `@playwright/test` devDep + `test:e2e` script;
    `.gitignore` — playwright runtime-artifact dirs.
  - `AdminUserDrawer.tsx` — `PRESET_OPTIONS` + `FieldSelect` exported so the harness
    mounts the real symbols.
- `projects/polymarket/crusaderbot/reports/forge/admin-preset-dropdown-fix.md` — this report.
- State sync: `state/PROJECT_STATE.md`, `state/CHANGELOG.md`.

## 7. What is working

- `npx tsc --noEmit` → **0 errors**; `npm run build` → **built in 6.18s** (prod bundle clean).
- `pytest tests/test_admin_console.py` → **59 passed** (incl. 3 new).
- `npm run test:e2e` (Playwright + real Chromium against the real component) →
  **E2E PASSED**: 7-option dropdown (6 presets + placeholder), candle_auto +
  playbook present with "Smart Strike"/"Playbook" labels, before/after screenshot
  written. (Operator-requested screenshot delivered:
  `webtrader/frontend/playwright/__screenshots__/preset-dropdown-before-after.png`.)
- `domain.preset` standalone assertion: `VISIBLE_PRESET_ORDER` == the 6 dropdown
  options, all `is_activatable`.
- No backend code change → zero backend regression surface.

### Before / after (dropdown options)

```
BEFORE: (unchanged) | close_sweep | safe_close | flip_hunter | weather_monitor
AFTER:  (unchanged) | candle_auto — Smart Strike (auto: 7 factors → close/safe/flip)
                    | close_sweep — Close Sweep
                    | safe_close — Safe Close
                    | flip_hunter — Flip Hunter
                    | weather_monitor — Weather Monitor
                    | playbook — Playbook (sports router, PAPER)
```

## 8. Known issues / constraints

- **e2e harness now exists (Playwright installed).** `cdn.playwright.dev` IS
  reachable under the network policy, so Chromium was installed and a Playwright
  e2e was added + run green (see §7). Implementation note: this project is ESM
  (`"type":"module"`), which trips the Playwright *test runner*
  ("did not expect test() to be called here" — module-registry split). The e2e
  therefore uses Playwright **as a library** (`e2e/run-preset-dropdown.mjs`)
  driving real Chromium — robust under ESM, same real component + screenshot. A
  follow-up could migrate to the runner (CT or a separate non-ESM test package)
  if standing UI coverage in CI is wanted; the Python CI job does not run it today.
- **Full persist-e2e** (selection → backend round-trip) needs the live API + DB +
  auth stack, which the harness deliberately avoids; the server-side persist
  contract is covered by the 3 backend tests instead.
- The admin drawer's preset list is a hand-maintained mirror of
  `presets.py PRESET_ORDER`; `test_admin_preset_dropdown_matches_canonical_registry`
  guards backend drift, but a future preset still needs a one-line dropdown edit.
  Sourcing the dropdown from `/autotrade/preset-availability` would remove the
  mirror entirely — optional follow-up.

## 9. Safety / invariants

Operator-facing admin UI only. No trading/risk/Kelly/LIVE-guard surface. No
secrets, asyncio-safe, no `phase*/`. No backend code change. Persisted values are
canonical preset keys already validated server-side.

Validation Handoff (NEXT PRIORITY):

```
WARP🔹CMD review required.
Source: projects/polymarket/crusaderbot/reports/forge/admin-preset-dropdown-fix.md
Tier: STANDARD
```
