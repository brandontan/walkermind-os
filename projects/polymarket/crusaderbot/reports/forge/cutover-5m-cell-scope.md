# WARP-78 — cutover verdict 5m-cell scope (BTC/5m + ETH/5m)

- Role: WARP•R00T
- Validation Tier: STANDARD (changes the cutover verdict's cell scope — decision-
  significant — but in the offline report tool only; no runtime/capital path).
- Claim Level: NARROW INTEGRATION (scope threaded through the report
  pipeline + tests; the `--from-db` re-run stays CMD-gated/data-gated).
- Validation Target: `report_cutover_holdout` evaluates §1.5/§1.7 over the
  confirmed 5m-first scope `{BTC/5m, ETH/5m}` so the gated re-run can PASS.
- Not in Scope: the runtime cutover routing wire (future PR after a PASS); the
  §1.7 verdict LOGIC (unchanged — only the cell set narrows); the re-run (gated).
- Branch: `WARP/cutover-5m-cell-scope`

---

## 1. What was built

CMD confirmed the cutover scope as **5m-first** (`BTC/5m` + `ETH/5m`); 15m is
dropped (Polymarket discontinued the `updown-15m` series — see
`reports/forge/15m-accrual-investigation.md`). But the renderer still evaluated
all 4 cells, and §1.7 PASS requires **every** target cell to meet the §1.5
minimum — so a re-run would have scored the two terminal 15m cells (11–13 rows)
as INCONCLUSIVE and **forced RETRY forever**, even with strong 5m results. This
lane scopes the verdict to the confirmed cells.

- **`scripts/report_cutover_holdout.py`**:
  - `CUTOVER_CELLS = ("BTC/5m", "ETH/5m")` — the confirmed scope.
  - `compute_report`, `apply_criteria`, `render_markdown` take
    `target_cells: Sequence[str] = CUTOVER_CELLS`. The overall aggregate, the
    §1.5 sample gate, the per-cell catastrophic gate, and every rendered table
    now range over the scoped cells only. **§1.7 verdict logic is unchanged** —
    only the cell set it applies to.
  - CLI `--cells` (default `BTC/5m,ETH/5m`) overrides the scope (e.g. if the
    venue reinstates 15m).
  - The report header now states the cutover scope + the 15m-drop reason.
  - Off-scope cells (15m, SOL/5m, UNKNOWN) are still computed but excluded from
    the overall and the verdict — never pollute the gated metric.
  - The committed template `reports/forge/cutover-holdout-template.md` is
    regenerated to the 2-cell scope.

## 2. Current system architecture

```
report_cutover_holdout --from-db --margin 0.015 [--cells BTC/5m,ETH/5m]
        │  fetch_settled_rows(data_source="paper_real")   (Lane 1 filter)
        ▼
compute_report(rows, target_cells=CUTOVER_CELLS)   overall = Σ scoped cells only
        ▼
apply_criteria(..., target_cells=CUTOVER_CELLS)    §1.5 + catastrophic over scoped cells
        ▼
§1.7 verdict (logic unchanged) → PASS / FAIL / RETRY
```

## 3. Files created / modified (full repo-root paths)

- Modified: `projects/polymarket/crusaderbot/scripts/report_cutover_holdout.py`
- Modified: `projects/polymarket/crusaderbot/tests/test_cutover_report_template.py`
- Modified (regenerated): `projects/polymarket/crusaderbot/reports/forge/cutover-holdout-template.md`
- Created: `projects/polymarket/crusaderbot/reports/forge/cutover-5m-cell-scope.md`
- State sync: `state/PROJECT_STATE.md`, `state/CHANGELOG.md`

## 4. What is working

- New test `test_5m_scope_passes_despite_terminal_15m`: strong 5m + terminal 15m
  → **PASS** under the default `CUTOVER_CELLS` scope, **RETRY** under the full
  4-cell scope (the exact failure mode this lane fixes).
- `test_overall_excludes_off_scope_cells`: 15m + SOL/5m present in the data but
  excluded from `overall`.
- Demo template renders the 2 scoped cells + the scope header; all 6 sections
  present; canonical rule keys; no `smart_strike`.
- 32 dependent tests pass; `ruff` clean.

## 5. Known issues

- The re-run is still **gated**: 5m must reach ≥200/cell (~80 now, ~12–14h) and
  CMD fires it. This lane only makes the gated run PASS-able.
- If Polymarket reinstates `updown-15m`, re-add it via `--cells` (or restore the
  4-cell default) and re-evaluate 15m inclusion.

## 6. What is next

- Hold for the gate. When 5m ≥200/cell: `ev_comparator --from-db`
  (`--data-source paper_real`) → `report_cutover_holdout --from-db --margin 0.015`
  (now scoped to the 5m cells) → §1.7 verdict → CMD cutover decision. On PASS,
  author the runtime cutover wire (`candle_auto`+`auto`+cell∈`{BTC/5m,ETH/5m}` →
  `EVComparator`, else router), consuming `CUTOVER_CELLS` for parity.

Suggested Next Step: WARP🔹CMD review; merged so the gated re-run is mechanical.
