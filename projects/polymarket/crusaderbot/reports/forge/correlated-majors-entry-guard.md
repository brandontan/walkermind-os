# WARP•FORGE Report — correlated-majors-entry-guard

- Validation Tier: MAJOR (RISK layer — entry gating on correlated assets)
- Claim Level: NARROW INTEGRATION (one new orchestrator risk gate + config knob + cluster constant; no execution/router/ledger change)
- Validation Target: the new `_gate_correlated_majors` step (3d-ii) in `_process_candidate`, its in-memory window helpers, the `CORRELATED_MAJORS_SAME_DIR_LIMIT` config knob, and the `CORRELATED_CRYPTO_MAJORS` cluster constant.
- Not in Scope: the gate's 13 risk steps (unchanged), TradeEngine/router/paper execution (unchanged), the max_concurrent count cap (verified correct, NOT modified), live activation, migrations (none).
- Suggested Next Step: WARP🔹CMD review + merge; confirm the cap=2 / cluster {BTC,ETH,SOL} / 120s window policy.

---

## 1. What was built

A new orchestrator-level RISK gate that caps how many **same-direction**
correlated crypto-majors (BTC/ETH/SOL) a single user may open within one
same-candle window — closing the correlation-concentration gap behind the
owner-reported prod loss pattern (qwneer8, BTC+ETH+SOL/5m: all three majors open
the same direction each candle and stop out together — three simultaneous
`sl_hit`).

Investigation first established what the bug is **not**. The premise that a
`max_concurrent` count race lets three positions slip past the per-user cap is
**false**, with code evidence:

- Candidates for a user are processed **sequentially**, one `await` at a time —
  `services/signal_scan/signal_scan_job.py:4427`
  (`for cand in _diversify_lib_candidates(...): await _process_candidate(...)`).
- The paper position row (`status='open'`) and the balance debit commit
  **synchronously** inside `async with conn.transaction()` before
  `router_execute` returns — `domain/execution/paper.py:40-76`.
- The fast scan loop **cannot overlap itself** —
  `scheduler.py:1189` (`max_instances=1, coalesce=True`).

Therefore gate step 7 (`_open_position_count`, `domain/risk/gate.py:567`) sees
the prior candidate's committed position and increments correctly; the per-user
cap (Conservative 5 / Balanced 12 / Aggressive 20) is already honored. Three
simultaneous entries are *within* that cap (3 < 5), so the count cap was never
the mechanism.

The genuine gap is **correlation concentration**: BTC/ETH/SOL move together, so
three same-direction candle entries behave like one 3×-leveraged directional bet
that the count cap cannot see. The new guard caps that directly.

## 2. Current system architecture

```
late_entry_v3 candidate (metadata["cell"] = "BTC/5m")
        |
signal_scan_job._process_candidate
        ├─ … gates 0–3d (unchanged) …
        ├─ 3d-ii  _gate_correlated_majors  ◄── NEW
        │          asset = _major_asset_from_candidate(cand)   # "BTC/5m" → "BTC"
        │          if asset ∈ CORRELATED_CRYPTO_MAJORS and
        │             _correlated_majors_recent_count(user, side) ≥ cap:
        │               skip "skipped_correlated_majors_concentration"
        ├─ … robustness / live-price / build signal …
        ├─ 4. TradeEngine.execute → 13-step risk gate → router → paper commit
        └─ 5. on accepted (inserted, non-duplicate) AND asset is a major:
                  _correlated_majors_record_entry(user, side, now)   # window++
```

The window is an **in-memory per-(user, side) rolling counter**
(`_correlated_majors_log`, `_CORRELATED_MAJORS_WINDOW_SEC = 120s`), recorded
only on accepted entries — so the gate performs **zero hot-path DB reads** (the
#1694 pool-wedge RCA pattern). It is a structural twin of the existing
`_gate_safe_close_direction` limiter, differing in three deliberate ways:
applies to **all** candle presets (correlation is a market property, not a preset
property), scopes to the BTC/ETH/SOL cluster only, and uses a short same-candle
window instead of the 1h safe_close window.

`same direction` = same `side` string: for "{Asset} Up or Down" candle markets
`yes`=up uniformly across the cluster, so two majors both `yes` are the same
directional bet. Opposite sides (a `yes` and a `no` major) partially hedge and
are counted under separate keys.

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/domain/risk/constants.py` — new
  `CORRELATED_CRYPTO_MAJORS = frozenset({"BTC","ETH","SOL"})` cluster constant + rationale.
- `projects/polymarket/crusaderbot/config.py` — new
  `CORRELATED_MAJORS_SAME_DIR_LIMIT: int = 2` knob + `field_validator`
  rejecting negatives at load (mirrors the safe_close knob trap).
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` —
  import the cluster constant; module-level window state + helpers
  (`_CORRELATED_MAJORS_WINDOW_SEC`, `_correlated_majors_log`,
  `_correlated_majors_recent_count`, `_correlated_majors_record_entry`,
  `_correlated_majors_reset_for_tests`, `_major_asset_from_candidate`);
  gate helper `_gate_correlated_majors`; wired as step 3d-ii in
  `_process_candidate`; record-on-accept in the success branch.

Created:
- `projects/polymarket/crusaderbot/tests/test_correlated_majors_limit.py` — 24 tests.

Report:
- `projects/polymarket/crusaderbot/reports/forge/correlated-majors-entry-guard.md` (this file).

State:
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`,
  `projects/polymarket/crusaderbot/state/CHANGELOG.md` updated.

## 4. What is working

- 43 tests pass (24 new + 19 existing `test_safe_close_direction_limit.py`
  regression — the shared in-memory-window pattern is intact). `ruff` clean on
  all four touched/created files.
- Behaviour verified end-to-end via `_process_candidate` mock-stack tests:
  - BTC → ETH → SOL same side, cap=2: first two reach the engine and record,
    the **third is blocked** (`test_full_cluster_sequence_caps_at_two`).
  - Opposite-side major bypasses a full same-side window
    (`test_gate_isolates_opposite_sides`).
  - Non-cluster asset (DOGE) bypasses the guard entirely and never records.
  - `CORRELATED_MAJORS_SAME_DIR_LIMIT=0` disables the gate; negatives rejected
    at config load.
  - Recorded only on a genuinely new accepted fill — an `inserted=False`
    concurrent ON CONFLICT skip and a `mode="duplicate"` result do **not**
    advance the counter.
- Default-OFF risk to existing behaviour is nil: the default cap is 2, which
  matches the owner directive; a user can still open two correlated majors.

## 5. Known issues

- The window is **process-local in-memory** (identical to the safe_close
  limiter). A process restart drops the counter; worst case is one extra
  correlated entry per (user, side) before it rebuilds — far cheaper than a
  per-candidate DB read, and consistent with the established pattern. The bot
  runs as a single Fly worker, so there is no multi-process divergence today.
- The 120s window is a fixed module constant (not a config knob). It comfortably
  isolates one 5m/15m candle's entry burst (all majors enter within
  late_entry_v3's final ~35s window) while resetting before the next candle. On
  a hypothetical ≤2m timeframe the window could bleed across two candles — which
  errs conservative (fewer correlated entries), the safe direction. If a faster
  candle timeframe is ever enabled, expose the window as a knob.
- The cluster membership is hard-wired to {BTC, ETH, SOL}. Adding future majors
  (e.g. XRP/DOGE candle markets) is a one-line constant edit.

## 6. What is next

- WARP🔹CMD review + merge (MAJOR Stop Condition — not self-merged).
- Confirm the policy: cap=2 same-direction, cluster {BTC,ETH,SOL}, 120s window.
  Note the deliberate trade-off — the guard blocks the 3rd same-direction major
  even when it passes every strategy rule (correlation safety > opportunity
  capture); the owner approved this.
- Post-merge paper observation: confirm scan logs show
  `skipped_correlated_majors_concentration` when a user with BTC+ETH+SOL selected
  takes a third same-side candle signal, and that two same-side entries still go
  through.
