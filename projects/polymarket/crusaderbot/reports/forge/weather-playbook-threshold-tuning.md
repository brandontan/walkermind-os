# WARP-80 sub-lane 1b — Weather + Playbook threshold-tuning report (v1, COARSE)

Role: WARP•R00T (analysis — REPORT ONLY, no code, no threshold change)
Validation Tier: **MINOR** (report only)
Claim Level: **FOUNDATION** (coarse baseline from current `scan_runs`; the sharp,
distance-aware refresh runs ~24h after sub-lane 1a accrues)
Validation Target: quantify the weather + playbook zero-entry starvation from the
data available TODAY, and define the threshold-tuning method 1a unlocks.
Not in Scope: any threshold change (this report RECOMMENDS only — WARP🔹CMD
decides separately); external-feed wiring (1c, deferred); ev_comparator /
scorer_trainer / orchestrator (WARP-79).
Suggested Next Step: merge sub-lane 1a (PR #1673), let `strategy_scan_observations`
accrue ~24h, then re-run this as **v2 (sharp)** for per-threshold entry-count +
EV-impact estimates → WARP🔹CMD threshold decision.

---

## 1. What was built

A coarse, read-only threshold-tuning baseline for the two opportunistic
strategies, plus the method the sharp refresh will use. Source: 7 days of live
`scan_runs` (Supabase `ykyagjdeqcgcktnpdhes`, 2026-05-31 → 2026-06-06). No code,
no DB writes, no threshold change.

### Headline

Both strategies dispatch and run `.scan()` on the ticks they are enabled, and
return **zero candidates every time** — confirmed opportunistic-edge starvation,
not a gate/bug (consistent with the #1664 diagnosis). **The data needed to
recommend a specific threshold relaxation — the distribution of how far each
candidate was from passing — does not exist in the DB today.** That distribution
is exactly what sub-lane 1a (`strategy_scan_observations`, PR #1673) begins
capturing. So v1 can quantify the starvation and frame the levers; it cannot yet
defend a number. None is fabricated.

## 2. Current system architecture / data picture

7-day aggregate (`scan_runs`, 4,790 runs, 2.38 avg users/run, ~718 markets seen/run):

| strategy | `:filter_or_no_match` total | runs dispatched | candidates | positions (all-time) |
|---|---:|---:|---:|---:|
| weather | 2,714 | 1,604 / 4,790 (~33%) | **0** | **0** |
| playbook | 348 | 348 / 4,790 (~7%) | **0** | **0** |
| late_entry_v3 | 4,222 | 2,642 | (the book) | 1,168 |

Daily dispatch is **intermittent**, but yield is uniformly 0:

| day | runs | weather dispatched | weather 0-yield | playbook dispatched | playbook 0-yield |
|---|---:|---:|---:|---:|---:|
| 05-31 | 452 | 145 | 145 | 0 | 0 |
| 06-01 | 693 | 481 | 481 | 0 | 0 |
| 06-02 | 579 | 352 | 352 | 0 | 0 |
| 06-03 | 707 | 411 | 411 | 118 | 118 |
| 06-04 | 859 | 27 | 27 | 29 | 29 |
| 06-05 | 791 | 0 | 0 | 0 | 0 |
| 06-06 | 709 | 188 | 188 | 201 | 201 |

Observations:
- **Weather** dispatches on ~1/3 of ticks but its dispatch count swings widely
  (481 → 27 → 0 → 188). The 06-05 zero-dispatch day means weather did not run its
  scan branch at all (flag-off window or no markets), distinct from "ran and found
  nothing". Every tick it DOES dispatch yields 0 candidates.
- **Playbook** only began dispatching 2026-06-03 (sports-sourcing #1596 deploy
  window) and is intermittent (118 / 29 / 0 / 201); again 0 candidates throughout.
- `skip_breakdown` holds only **risk-gate** skips (`skipped_open_position_exists`
  ×1363, `skipped_liquidity` ×17, `skipped_stale_tob` ×3) — **none** of the
  per-filter edge skips (EV / price / quality / module-abstain). The binding
  constraint is therefore invisible from the DB today. **This is the gap 1a fills.**

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/reports/forge/weather-playbook-threshold-tuning.md` — this report
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `state/CHANGELOG.md` — synced

## 4. What is working (what v1 can conclude)

- **The starvation is real and persistent, not a transient/deploy artifact** — 0
  yield across 7 days and every dispatch day.
- **It is not a gate/flag defect** — `filter_or_no_match` (strategies ran), not
  `strategy_disabled`; corroborates #1664.
- **The levers per strategy are now precisely identified:**
  - **Weather** = two opportunistic edge bars — `min_ev = 0.10` (floor) and
    `max_price = 0.45` (ceiling). These are the tunable knobs; 1a now records each
    candidate's `distance_to_threshold` + `would_pass_at_threshold` at −10/−25/−50%
    against both, so v2 can count hypothetical entries at each relaxation.
  - **Playbook** = primarily **feed darkness**, not a numeric threshold. 2 of 4
    alpha modules (injury_alpha, public_fade) abstain on the default `NullFeed`;
    only closing_edge (Gamma consensus) + sharp_money (on-chain flow) can fire.
    1a stamps `module_state` (live/null_feed) per abstain, confirming this from the
    DB. **The playbook lever is feed activation (sub-lane 1c, DEFERRED), not a
    threshold cut** — lowering closing_edge's `min_edge` is a possible secondary
    knob but secondary to re-arming the dark modules.

## 5. Known issues (why v1 is coarse)

- **No distance distribution yet.** v1 cannot estimate entry counts at −10/−25/−50%
  thresholds or EV impact — that needs `strategy_scan_observations` (1a) data. Any
  numeric recommendation today would be fabricated; none is given.
- **Dispatch ≠ constant.** Weather/playbook dispatch swings with flag state and
  market availability (e.g. 06-05 = 0 weather dispatch). v2 must normalize
  per-dispatch (per market reaching the gate), which 1a captures directly, rather
  than per-tick.
- **EV-impact estimate needs an analogue.** Step 3 of the spec (EV per
  would-be-entry) has no weather/playbook realized history (0 positions); v2 will
  have to borrow an EV-per-entry analogue or report entry-count deltas only and
  defer the EV figure — flagged for the CMD threshold decision.

## 6. What is next (the v2 sharp method, post-1a)

Once 1a has ~24h of `strategy_scan_observations`:

1. **Weather, per cell/strategy:** distribution of `distance_to_threshold` at
   `binding_filter='ev'` and `='price'`; count `would_pass_at_threshold` TRUE at
   −10% / −25% / −50% (already pre-computed per row) → hypothetical entries at each
   level, straight from SQL.
2. **EV impact (if derivable):** for the would-be entries, estimate EV per entry
   from the recorded `metric_value` (the modelled EV at entry) × count; otherwise
   report entry-count deltas and mark EV `N/A — no realized analogue`.
3. **Recommendation per strategy/module:** which threshold to lower and by how
   much, with the expected entry-count effect — **as a recommendation to WARP🔹CMD,
   who decides.** Scope lock: a recommendation that would degrade existing strategy
   quality is a STOP-and-ask-CMD condition, not an auto-apply.
4. **Playbook:** v2 will quantify abstain reasons via `module_state`; the primary
   recommendation remains feed activation (1c) gated on the CMD licensing/cost
   discussion, not a threshold cut.

**No threshold is changed by this lane.** v1 = baseline + method; v2 = sharp
recommendation for the CMD decision.

---

Validation Handoff (NEXT PRIORITY):

```
WARP🔹CMD review required.
Source: projects/polymarket/crusaderbot/reports/forge/weather-playbook-threshold-tuning.md
Tier: MINOR
```
