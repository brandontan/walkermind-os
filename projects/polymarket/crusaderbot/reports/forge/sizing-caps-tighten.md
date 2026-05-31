# WARP•FORGE Report — sizing-caps-tighten

**Validation Tier:** MINOR
**Claim Level:** NARROW INTEGRATION
**Validation Target:** `config.MAX_SINGLE_POSITION_PCT` and `config.MAX_TOTAL_EXPOSURE_PCT` defaults
**Not in Scope:** Kelly sizing logic, risk gate steps, per-user capital_allocation_pct settings

---

## 1. What Was Built

Two config defaults tightened to close WARP-48 B3 (sizing caps confirm):

| Knob | Old | New | Rationale |
|---|---|---|---|
| `MAX_SINGLE_POSITION_PCT` | `0.10` (10%) | `0.05` (5%) | Hard ceiling after Kelly. Kelly `a=0.25` produces ~1-5% effective sizing on real signals; 10% was too loose for LIVE (single bad trade = -10% of balance). 5% gives Kelly room to breathe while capping runaway sizing. |
| `MAX_TOTAL_EXPOSURE_PCT` | `0.80` (80%) | `0.60` (60%) | Aggregate open-exposure limit. 80% could lock near-full capital in simultaneous positions. 60% keeps a 40% cash buffer; balances between the directive spec (~50%) and practical multi-position operation. |

Both knobs are env-overridable (`MAX_SINGLE_POSITION_PCT`, `MAX_TOTAL_EXPOSURE_PCT`) — no redeploy needed to adjust.

---

## 2. Current System Architecture

No architecture change. The two constants feed `validate_risk_caps` which runs at **step 0** (Hard risk caps — fail-fast before any gate logging) in `domain/risk/gate.py:evaluate`. The 13-step risk gate chain is unchanged.

---

## 3. Files Created / Modified

| File | Change |
|---|---|
| `projects/polymarket/crusaderbot/config.py` | `MAX_SINGLE_POSITION_PCT` 0.10→0.05, `MAX_TOTAL_EXPOSURE_PCT` 0.80→0.60 (lines 217-218) |
| `projects/polymarket/crusaderbot/reports/forge/sizing-caps-tighten.md` | This report |

---

## 4. What Is Working

- `py_compile` clean on `config.py`
- `ruff check` clean on `config.py`
- No test pins the old defaults (all `0.10` references in tests refer to `capital_allocation_pct` or `sl_pct` — unrelated per-user knobs)
- All risk gate logic unchanged; only the ceiling values updated
- Kelly sizing (`a=0.25`) and per-user `capital_allocation_pct` are unaffected

---

## 5. Known Issues

None introduced. If 5% ever clips a legitimately high-Kelly signal, operator can raise via `MAX_SINGLE_POSITION_PCT=<value>` env var without redeploy.

---

## 6. What Is Next

1. **Merge + deploy** — caps enforce on next scan tick
2. **Monitor** — confirm positions are sized within the new 5% ceiling via `positions.size_usdc / balance_usdc` spot checks after first few trades
3. **Pre-LIVE** — sizing caps are now aligned for safe LIVE operation; remaining LIVE gate: B1 (CB 7d paper window), full activation guard sequence in `state/LIVE_READINESS.md`

**Suggested Next Step:** WARP🔹CMD review + merge.

---

**Validation Tier:** MINOR
**Claim Level:** NARROW INTEGRATION
