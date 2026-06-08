# WARP-86 Phase 0b — AUTO Risk Profile

- Branch: `WARP/warp-86-auto-profile` (from `origin/main` HEAD #1707)
- Role: WARP•FORGE
- Validation Tier: **MAJOR** (risk / capital / async core path)
- Claim Level: **NARROW INTEGRATION** (new profile wired into the existing risk gate + API + sizing path; no new runtime engine)
- Validation Target: the AUTO risk profile — Kelly a=0.25 sizing (reused gate clamp), the candle_auto entry constraint at the gate, strategy-owned TP/SL delegation (1.5/0.5), and API acceptance of `risk_profile='auto'`.
- Not in Scope: any EV-scoring engine (Phase 0c, data-gated); `domain/strategy/` exit-hook logic (already correct); migrations (none — `risk_profile` is already VARCHAR); `SCORER_ACTIVE` / `ORCHESTRATOR_ACTIVE` / `ENABLE_LIVE_TRADING`; the Kelly a=0.25 value; `balanced` / `aggressive` behaviour; the live-activation (WARP-92) code.
- System mode: PAPER throughout.

---

## 1. What was built

A single EV-driven risk profile, `'auto'`. A user selecting `risk_profile='auto'`
gets the EV-validated behaviour with **no manual configuration**:

- **Kelly a=0.25 sizing** — `PROFILES['auto']['kelly']=0.25` flows through the
  EXISTING gate sizing line `min(profile.get("kelly"), K.KELLY_FRACTION)`; no
  Kelly value is duplicated, parameterised, or exposed. Full Kelly (1.0) remains
  impossible (clamped by the global `KELLY_FRACTION` hard cap).
- **`candle_auto` entry constraint** — a new gate step-4 check rejects any AUTO
  candidate whose active preset is not `candle_auto`, so AUTO only ever trades
  the `candle_auto → late_entry_v3` EV path. "Skip (do not trade)" is a clean
  gate rejection (`auto_requires_candle_auto`), never an exception.
- **Strategy-owned TP/SL (1.5/0.5)** — AUTO's runtime exit thresholds come from
  `late_entry_v3.default_tp_sl()` via the EXISTING `signal_scan_job` NULL→
  strategy-default fallback (WARP-85/90). No TP/SL is hardcoded in the risk
  stage; the `PROFILE_TP_SL['auto']` entry only seeds bootstrap.
- **API acceptance** — `risk_profile='auto'` is accepted (no 400) on both
  risk-profile write paths.

### DESIGN DECISION (flagged for SENTINEL / WARP🔹CMD review)

The directive specified only **`kelly=0.25`** for AUTO. AUTO's **non-Kelly caps**
(`max_pos_pct`, `max_concurrent`, `daily_loss`, `min_edge_bps`, `min_liquidity`,
`max_days`) **MIRROR `balanced`** — i.e. AUTO = balanced capital/concurrency/loss
discipline + the maximum fractional Kelly. This is a deliberate FORGE decision
made because the directive gave no other values; CMD can retune these at review
without touching the AUTO mechanism.

---

## 2. Current system architecture

```
user_settings.risk_profile = 'auto'
        │
        ▼
signal_scan orchestrator ── TradeSignal(risk_profile='auto', active_preset='candle_auto', tp/sl NULL)
        │                         │
        │                         └─ NULL TP/SL → _strategy_default_tp_sl('late_entry_v3') → (1.5, 0.5)   [STRATEGY-owned, existing]
        ▼
TradeEngine._build_gate_context ── active_preset threaded into GateContext   [+1 line]
        ▼
RISK GATE (domain/risk/gate.py evaluate)
   step 4  strategy availability  → 'auto' ∈ STRATEGY_AVAILABILITY['late_entry_v3']
   step 4  AUTO entry constraint  → active_preset != 'candle_auto' ? REJECT 'auto_requires_candle_auto'   [NEW]
   step 13 Kelly sizing           → min(PROFILES['auto']['kelly']=0.25, KELLY_FRACTION) = 0.25            [REUSED, unchanged]
        ▼
EXECUTION (paper) — exits applied by late_entry_v3 using its own 1.5/0.5
```

The pipeline order (`DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION →
MONITORING`) is preserved: TP/SL stays a STRATEGY-stage concern; the RISK stage
only sizes capital and fences the entry path.

---

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/domain/risk/constants.py` — `PROFILES['auto']` (kelly=0.25, other caps mirror balanced); `PROFILE_TP_SL['auto']` (0.40/1.5/0.5 bootstrap seed); `'auto'` added to `STRATEGY_AVAILABILITY['late_entry_v3']` only.
- `projects/polymarket/crusaderbot/domain/risk/gate.py` — new optional/defaulted `GateContext.active_preset`; new step-4 AUTO entry constraint (`auto_requires_candle_auto` reject + `logger.warning` + `_log`). Kelly line and TP/SL handling unchanged.
- `projects/polymarket/crusaderbot/services/trade_engine/engine.py` — `_build_gate_context` threads `active_preset=signal.active_preset` (one line).
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` — `'auto'` added to `_VALID_RISK_PROFILES` (covers both `set_risk_profile` and the user-update validation paths).
- `projects/polymarket/crusaderbot/webtrader/backend/schemas.py` — `RiskProfileRequest.profile` comment updated to note `'auto'` (membership enforced server-side via `_VALID_RISK_PROFILES`, not a schema enum — no behavioural change).
- `projects/polymarket/crusaderbot/tests/test_robustness_gate.py` — `_signal_ns` mock gains `active_preset=None` (mock-gap fix for the new threaded field).

Created:
- `projects/polymarket/crusaderbot/tests/test_auto_risk_profile.py` — 12 hermetic tests.

---

## 4. What is working

- `profile_or_default("auto")["kelly"] == 0.25`; gate clamp `min(profile["kelly"], KELLY_FRACTION) == 0.25` (Kelly path reused, not duplicated).
- AUTO's non-Kelly caps verified equal to `balanced` (design-decision pin).
- AUTO + non-`candle_auto` preset (`None`, `safe_close`) → gate rejects `auto_requires_candle_auto` at step 4 with a logged warning; AUTO + `candle_auto` and any non-AUTO profile pass step 4 (reach step 5).
- AUTO TP/SL sourced from `late_entry_v3.default_tp_sl() == (1.5, 0.5)` via the existing `_strategy_default_tp_sl` resolver — not a risk-stage hardcode.
- `'auto'` present only in `STRATEGY_AVAILABILITY['late_entry_v3']` (no other strategy_type).
- API: `set_risk_profile(profile='auto')` returns `{risk_profile:'auto', capital_alloc_pct:0.40, tp_pct:1.5, sl_pct:0.5}` (no 400).
- `pytest projects/polymarket/crusaderbot/tests/ -q` → **3149 passed, 15 skipped, 4 failed** (the 4 are the PRE-EXISTING unrelated `test_clob_pysdk` failures = missing optional `polymarket` module).
- `ruff check .` → **All checks passed!**

---

## 5. Known issues

- None introduced. The 4 `test_clob_pysdk` failures are pre-existing and unrelated (missing optional `polymarket` dependency in this environment).
- DESIGN DECISION open for review (see §1): AUTO's non-Kelly caps mirror `balanced`; CMD may retune at SENTINEL review.

---

## 6. What is next

- WARP•SENTINEL validation (MAJOR) of this lane before merge — see the Validation Handoff below.
- (Out of scope, Phase 0c) EV-scoring engine — data-gated, separate lane.

---

## Validation Handoff (NEXT PRIORITY)

```
WARP•SENTINEL validation required for WARP-86 Phase 0b (AUTO risk profile) before merge.
Source: projects/polymarket/crusaderbot/reports/forge/warp-86-auto-profile.md
Tier: MAJOR
```

## Suggested Next Step

WARP•SENTINEL: confirm (a) AUTO Kelly resolves to 0.25 via the reused clamp with
full Kelly never exposed; (b) the `candle_auto` entry constraint is a clean
reject (no exception) and only AUTO is fenced; (c) TP/SL remains strategy-owned;
(d) `GateContext.active_preset` is byte-compatible for existing construction
sites; (e) API accepts `'auto'`. Then return to WARP🔹CMD with the
balanced-caps design decision for a retune-or-keep ruling.
