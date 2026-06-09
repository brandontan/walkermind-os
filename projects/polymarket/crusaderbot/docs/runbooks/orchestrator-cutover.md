# Orchestrator Cutover Procedure — CrusaderBot (WARP-78)

**Owner:** Operator (Bayue Walker)
**Audience:** WARP🔹CMD operator on call.
**Last reviewed:** 2026-06-07 Asia/Jakarta — WARP-78 cutover-readiness lane.

This runbook covers cutting `candle_auto` + rule `auto` ("Smart Strike")
users over from the **precedence router** to the **EV-comparator
orchestrator**, plus the emergency fallback. The cutover is **code-level**
(a PR merge + Fly CD deploy), NOT an operator flag flip — but a no-redeploy
runtime kill-switch (`ORCHESTRATOR_KILL_SWITCH`) gives instant fallback to
the router if the orchestrator misbehaves.

> **Architecture (corrected, WARP-78):** the orchestrator engages implicitly
> when a user has `active_preset = candle_auto` AND `rule = "auto"`. Pinned
> rules (`close_sweep` / `safe_close` / `flip_hunter`) and the other presets
> (`weather_monitor` / `playbook`) NEVER route via the orchestrator.
> `ORCHESTRATOR_ACTIVE`-as-Fly-secret is obsolete.

> **Scope note:** this lane shipped the kill-switch + this runbook. The
> **cutover PR** that wires `candle_auto`+`auto` → `EVComparator.select` in
> `late_entry_v3` is a SEPARATE PR, merged only after Track C PASS (see §1).
> The gate that PR consults is `ev_comparator.orchestrator_routes(preset, rule)`,
> which already honours the kill-switch shipped here.

---

## 1. Pre-cutover checklist (ALL must hold)

- [ ] `paper_real` settled rows **≥ 200 per cell** for all 4 target cells
      (`BTC/5m`, `BTC/15m`, `ETH/5m`, `ETH/15m`).
- [ ] Track C decision criteria **signed off by WARP🔹CMD** (margin option
      picked) — `reports/forge/cutover-decision-criteria.md`.
- [ ] Track D holdout report run on real data returns **PASS**
      (`python scripts/report_cutover_holdout.py --from-db --margin <C1|C2|C3>`)
      — no catastrophic cell, overall 95% CI excludes 0, margin met.
- [ ] The real EV model exists + is committed:
      `config/ev_comparator_model.json` generated via
      `python -m domain.strategy.ev_comparator --from-db`. **Without this file
      the comparator loads `neutral()` and abstains on every candle — the
      orchestrator would route `candle_auto`+`auto` users into ZERO trades.**
- [ ] Kill-switch verified reachable + currently OFF (see §4 to read it).
- [ ] App healthy: `curl -fsS https://crusaderbot.fly.dev/health | jq '.status,.mode'`
      → `"ok"`, `"paper"`.

If any item fails → **do not cut over.** A failed holdout is RETRY (accrue
more data) or FAIL (Phase 3 iterate), per Track C.

---

## 2. Cutover sequence

```bash
# 1. Merge the cutover PR (the one that wires candle_auto+auto -> orchestrator
#    selection in late_entry_v3, consuming ev_comparator.orchestrator_routes).
#    WARP🔹CMD merges to main.

# 2. Fly CD auto-deploys on merge to main (.github/workflows/crusaderbot-cd.yml).
#    Confirm the release:
flyctl releases list -a crusaderbot | head -3
curl -fsS https://crusaderbot.fly.dev/health | jq '.status, .version'
# version = the 12-char git short SHA of the cutover merge commit.
```

The deploy carries: the routing wire, `config/ev_comparator_model.json`, and
the kill-switch (default OFF). No secret flip is required.

---

## 3. Verification — first 30 minutes

```bash
# 1. Confirm the orchestrator is engaging for candle_auto+auto users.
#    Tail for the decision log emitted by the cutover wire:
flyctl logs -a crusaderbot | grep -E "orchestrator_decision|ev_comparator"
#    Healthy: orchestrator_decision lines for candle_auto+auto users naming the
#    selected rule (close_sweep/safe_close/flip_hunter) or an abstain.

# 2. Confirm NO leak onto pinned-rule / other-preset users:
#    pinned candle_auto users + weather_monitor/playbook users must show the
#    SAME selection behaviour as before (router / their own strategy). Any
#    orchestrator_decision line for a NON-(candle_auto+auto) user is a bug ->
#    engage the kill-switch (§4) and revert.

# 3. Per-cell sanity — no immediate catastrophic divergence vs the router.
#    Watch the first trades per cell; if any cell's orchestrator picks are
#    visibly bleeding vs the prior router behaviour, engage the kill-switch.
```

Healthy vs warning:

| Signal | Healthy | Warning → consider kill-switch |
| --- | --- | --- |
| `orchestrator_decision` lines | only for `candle_auto`+`auto` users | appear for pinned / other-preset users |
| Selected rule mix | spread across rules, some abstains | 100% one rule, or abstaining on every candle (model missing/empty) |
| Per-cell early EV | in line with the holdout report | a cell sharply worse than the router |

---

## 4. Emergency rollback — INSTANT, no redeploy (preferred)

The kill-switch forces `candle_auto`+`auto` users back to the precedence
router within the runtime-config cache window (≤30 s for the worker process;
immediate in the process that writes it). No deploy, no restart.

```bash
# ENGAGE (orchestrator OFF -> router):
#   Web admin (preferred) — admin-gated + audited:
#   PATCH https://crusaderbot.fly.dev/api/web/admin/settings/ORCHESTRATOR_KILL_SWITCH
#         body: {"value": true}

#   SQL fallback (if the admin UI is unavailable):
#   INSERT INTO system_settings (key, value, updated_at)
#   VALUES ('cfg:ORCHESTRATOR_KILL_SWITCH', 'true', NOW())
#   ON CONFLICT (key) DO UPDATE SET value='true', updated_at=NOW();

# CONFIRM engaged:
#   GET https://crusaderbot.fly.dev/api/web/admin/settings
#   -> ORCHESTRATOR_KILL_SWITCH effective=true, overridden=true

# RESUME (orchestrator back ON):
#   PATCH .../admin/settings/ORCHESTRATOR_KILL_SWITCH  body: {"value": false}
#   or DELETE .../admin/settings/ORCHESTRATOR_KILL_SWITCH  (revert to env default)
```

**Operator log:**

```
[YYYY-MM-DD HH:MM Asia/Jakarta] ORCHESTRATOR_KILL_SWITCH=ON via <admin|sql> — reason: ___
[YYYY-MM-DD HH:MM Asia/Jakarta] router fallback confirmed in logs within Δt = ___ s
```

Precedence + fail-safe (mirrors `SCAN_SNAPSHOT_ENABLED`, #1663): DB override →
env/Fly default → code default `False`. A read error fails safe to the env
default. The orchestrator and the overlay read the same DB, so a transient
blip is covered by the 30 s cache; a sustained DB outage reverts to the env
default — for which §5 provides the redeploy-proof backstop.

---

## 5. Hard rollback (kill-switch insufficient — e.g. DB outage)

Use only if the runtime toggle cannot be trusted (sustained DB outage) or a
code defect is implicated.

```bash
# Option A — redeploy-proof kill-switch backstop (survives a DB outage):
flyctl secrets set ORCHESTRATOR_KILL_SWITCH=true -a crusaderbot   # -> redeploy
#   The env/Fly default becomes the floor the DB overlay layers on; the
#   orchestrator stays OFF even if system_settings is unreadable.

# Option B — revert the cutover PR + redeploy (removes the routing wire):
#   git revert <cutover-merge-sha>  -> PR -> merge -> Fly CD
#   See rollback-procedure.md §3 for the image/commit rollback paths.
```

After a hard rollback, leave a `state/PROJECT_STATE.md` `[KNOWN ISSUES]`
entry until the root cause is fixed in a forward lane.

---

## 6. Communication template (internal status only — not multi-user yet)

```
[CUTOVER] Smart Strike orchestrator — candle_auto + auto
Status   : LIVE (paper) since <HH:MM Asia/Jakarta>, release <sha>
Decision : Track C PASS — margin <C1|C2|C3>, overall EV/trade Δ=<+x.xxx>
           (95% CI [<lo>, <hi>]); no catastrophic cell.
Scope    : candle_auto+auto users only. Pinned rules + weather/playbook
           unchanged. Paper mode — no real capital.
Fallback : ORCHESTRATOR_KILL_SWITCH (runtime toggle) → router in ≤30s.
Watch    : first 24h per-cell EV vs router; kill-switch armed.
```

---

## 7. References

- Kill-switch gate: `projects/polymarket/crusaderbot/domain/strategy/ev_comparator.py`
  (`orchestrator_routes`, `orchestrator_kill_switch_active`).
- Runtime overlay: `projects/polymarket/crusaderbot/domain/ops/runtime_config.py`
  (`RUNTIME_SETTINGS["ORCHESTRATOR_KILL_SWITCH"]`, `set_override`, `resolve_bool`).
- Env backstop: `projects/polymarket/crusaderbot/config.py` (`ORCHESTRATOR_KILL_SWITCH`).
- Admin toggle endpoints: `projects/polymarket/crusaderbot/webtrader/backend/router.py`
  (`PATCH/DELETE /admin/settings/{key}`, `GET /admin/settings`).
- Decision criteria: `reports/forge/cutover-decision-criteria.md` (Track C).
- Holdout report renderer: `scripts/report_cutover_holdout.py` (Track D).
- Pipeline dry-run proof: `reports/forge/cutover-pipeline-dryrun.md` (Track A).
- Deploy rollback paths: `docs/runbooks/rollback-procedure.md`.
