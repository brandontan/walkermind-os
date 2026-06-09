# WARP•R00T — decompose-process-candidate (Lane 4 / C-4)

**Branch:** `WARP/ROOT/decompose-process-candidate`
**Role:** WARP•R00T (system hardening)
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** the orchestration shape of `services/signal_scan/signal_scan_job._process_candidate`. Closes C-4 by extracting 7 self-contained pre-execution gates into named helper functions so each can be unit-tested in isolation and PR diffs can isolate gate edits from surrounding orchestration.
**Not in Scope:** any behavioural change to gate semantics (every helper preserves the original logic 1:1), the crash-recovery resume block (already documented + self-contained), the bankroll circuit breaker (already delegates to `_evaluate_bankroll_circuit_breaker`), LIVE live-fire validation.

---

## 1. What was built

`_process_candidate` had grown to ~866 lines as each new pre-execution gate was added inline. After C-4 the function is a 604-line orchestrator that delegates to seven named helpers. Total line reduction: **−262 lines (−30%)** on the orchestrator; net codebase change is the helpers + tests (cleanly testable in isolation now).

Each extracted helper follows the same contract:

```python
def _gate_<name>(...) -> str | None:
    """None → continue; str → skip reason that the orchestrator logs + returns."""
```

The orchestrator pattern is now uniform:

```python
_skip = _gate_<name>(...)
if _skip is not None:
    if telemetry is not None:
        telemetry.record_skip(_skip)
    return
```

Helpers extracted (all in `domain/risk/`... no — in `services/signal_scan/signal_scan_job.py`):

1. **`_gate_signal_freshness`** — reject publication-backed signals older than `_MAX_SIGNAL_AGE_SECONDS` (30 min). Pub-uuid-scoped.
2. **`_gate_target_price_drift`** — reject when cached DB price has drifted `> _MAX_TARGET_DRIFT_PCT` (25%) from the signal's target. Pub-uuid-scoped; side-fallback-aware.
3. **`_gate_liquidity_filter`** — reject markets below the user's configured `min_liquidity_threshold`.
4. **`_gate_tob_freshness`** — reject when orderbook snapshot age exceeds `TOB_STALE_MS` (default 2s). Scoped to candidates carrying `metadata["entry_price_ts"]`. Config-read failure falls back to 2000ms with a warning (AGENTS.md zero-silent-failures).
5. **`_gate_complete_set_edge`** — reject when complete-set edge < `MIN_COMPLETE_SET_EDGE`. Scoped to candidates carrying `metadata["complete_set_edge"]`. Unparseable stamp → warning + bypass (never silently reject).
6. **`_gate_candle_tick_alignment`** — reject candle-market live prices not on the 0.01 CLOB tick (Gamma seed/midpoint contamination). Scoped to `updown` slugs only — longshot markets with legitimate sub-cent prices bypass.
7. **`_gate_fill_band`** — reject fills outside `[fav_price_min, fav_price_max)`. No-ops for candidates without the band stamp.
8. **`_gate_safe_close_direction`** — cap safe_close per-(user,side) entries within the rolling 1h window. No-ops for other presets.

What stays inline in `_process_candidate`:

- Stage 0 crash-recovery resume (well-commented, already a single `if stale is not None:` block; extracting it adds ceremony without adding clarity — uses 7 local bindings from `row` + `stale` + `market`)
- Bankroll CB (delegates to `_evaluate_bankroll_circuit_breaker`; the inline portion is config read + persist-on-transition logic that shares `_uid_str` / `_cb_enabled` with the post-build step)
- Market lookup / price-resolution entry points (already 3-line helper calls)
- Imbalance override (mutates `cand` via `dataclasses.replace`; the side-flip touches multiple downstream branches via `_imbalance_override_active`)
- Step 5 post-execution record (~70 lines; mostly direct DB calls already routed through `_insert_execution_queue` / `_mark_executed`)

## 2. Current system architecture

```
_process_candidate (orchestrator, 604 lines)
├── stage 0 — crash-recovery resume (inline)
├── stage 0a — bankroll CB (inline, helpers already extracted)
├── stage 1 — pub dedup (existing helper)
├── stage 1a-2 — imbalance override (inline transformer)
├── stage 1b — open-position dedup (existing helpers)
├── stage 1c — _gate_signal_freshness                ← extracted
├── stage 2 — market lookup (existing helper)
├── stage 2b — _gate_target_price_drift              ← extracted
├── stage 2c — _gate_liquidity_filter                ← extracted
├── stage 3 — build TradeSignal + resolve fill price
├── stage 3b-0 — _gate_tob_freshness                 ← extracted
├── stage 3b-0a — _gate_complete_set_edge            ← extracted
├── stage 3b-i — _gate_candle_tick_alignment         ← extracted
├── stage 3c — _gate_fill_band                       ← extracted
├── stage 3d — _gate_safe_close_direction            ← extracted
├── stage 4 — TradeEngine.execute (inline orchestration)
└── stage 5 — post-execution record (inline)
```

Every extracted helper is now individually unit-tested without DB, without
broker, without TradeEngine — see `tests/test_process_candidate_gates.py`.

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` — added 7 `_gate_*` helpers (~330 lines), replaced 7 inline blocks with helper calls (`_process_candidate` 866 → 604 lines)
- `projects/polymarket/crusaderbot/tests/test_tob_freshness_gate.py` — updated 4 source-text pins to inspect `_gate_tob_freshness` while still verifying the orchestrator routes through it
- `projects/polymarket/crusaderbot/tests/test_complete_set_edge_gate.py` — same pattern, 4 source-text pins updated to inspect `_gate_complete_set_edge`
- `projects/polymarket/crusaderbot/tests/test_flip_hunter_stale_price_fix.py` — 2 source-text pins updated to inspect `_gate_candle_tick_alignment`

Created:
- `projects/polymarket/crusaderbot/tests/test_process_candidate_gates.py` — 34 hermetic unit tests covering every helper's contract (pass/skip path, scoping conditions, config fallback semantics)
- `projects/polymarket/crusaderbot/reports/forge/decompose-process-candidate.md` — this report

## 4. What is working

- `pytest tests/test_process_candidate_gates.py` — 34/34 pass (≥ 3 tests per helper covering happy path, scoping bypass, edge cases)
- `pytest tests/test_signal_scan_job.py` — 74/74 pass (behavioural integration unchanged)
- `pytest tests/test_tob_freshness_gate.py tests/test_complete_set_edge_gate.py tests/test_flip_hunter_stale_price_fix.py` — 49/49 pass (source pins + behavioural integration)
- Full project suite: **2264 passed** (was 2228 before this lane). 3 pre-existing SDK-gap failures only (`poly_eip712_structs`, `web3.py` Safe address) — same baseline as merged Lanes 1+2+3. Zero regression.
- `ruff check` + `py_compile` clean on the changed module.
- Behaviour preservation is exact: every helper reproduces the original inline logic line-for-line, including the structured-log payloads, fallback values, and AGENTS.md zero-silent-failures handling.

## 5. Known issues

None introduced by this lane.

- The remaining inline stages (crash-recovery, bankroll CB, imbalance override, post-execution record) are intentionally left in place — extracting them would either add ceremony without clarity gain (stages 0 + bankroll) or require threading too many locals (imbalance override, post-execution). They're already cleanly separated by stage comments.
- A future lane could move all `_gate_*` helpers into a dedicated module (`services/signal_scan/gates.py`) if a second consumer ever needs them — not justified yet.

## 6. What is next

- **Lane 5 — LIVE live-fire validation** (`USE_REAL_CLOB=True` end-to-end on a small cap, then flip `EXECUTION_PATH_VALIDATED`). MAJOR tier, owner-gated + SENTINEL required. This is the last lane before the public LIVE flip.
- **Pre-LIVE env tuning** (operator action before flip): relax `MAX_DAILY_LOSS_USD` and `MAX_TOTAL_EXPOSURE_PCT` in Fly secrets so per-profile / per-user limits become the visible truth at LIVE.
- Optional follow-up: surface `max_concurrent_override` (Lane 3) in the WebTrader customize form + Telegram parity.

---

**Suggested Next Step:** WARP🔹CMD review + merge of `WARP/ROOT/decompose-process-candidate` (STANDARD, NARROW INTEGRATION). No SENTINEL required per CLAUDE.md — pure code organization, every existing test still passes. After merge: Lane 5 live-fire validation is the final gate before public LIVE.
