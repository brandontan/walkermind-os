# WARP•R00T — correlated-majors cap made DB-authoritative + default 1

- Validation Tier: MAJOR (RISK layer — entry concentration on real correlated capital)
- Claim Level: NARROW INTEGRATION (one new DB read in the scan hot path + one config default; no execution/settlement/key path touched)
- Validation Target: the correlated crypto-majors same-direction cap is enforced across process restarts / multiple scan workers, and defaults to 1.
- Not in Scope: P&L computation (verified correct — see §5), the SL-cap paper convention, the per-user execution lane, ENABLE_LIVE_TRADING, Kelly/risk constants.
- Suggested Next Step: WARP🔹CMD review; deploy lands via Fly CD on merge. No config flip required (default already 1).

---

## 1. What was built

Owner-reported (screenshot, 2026-06-10): on one 5-minute candle the bot opened
**three** same-direction crypto-major positions — BTC + ETH + SOL all "YES" —
which then stopped out together at an identical −$13.69 each. The owner's
instinct ("I don't think it's possible to lose 3 orders together the same
amount") was correct: three ~95%-correlated assets entered as one 3x-leveraged
directional bet and reversed as a cluster.

### Root cause (code-confirmed)

The correlated-majors guard (`_gate_correlated_majors`, default cap 2 from
#1725) kept its counter **only in a process-local in-memory dict**
(`_correlated_majors_log`, `signal_scan_job.py:609`). Main received ~10 Fly CD
redeploys on 2026-06-10 (every merge → container restart). A restart **mid-candle
wipes that dict**, so the next same-direction major reads count 0 and opens —
defeating the cap. This matches the screenshot exactly: 3 majors in the early
candle (post-restart window reset), 2 in later candles (cap holding within a
single process lifetime).

### Fix

1. **DB-authoritative count** — new `_open_correlated_majors_count(user_id, side)`
   counts the user's currently-open same-direction BTC/ETH/SOL candle positions
   straight from `positions ⋈ markets` (slug head match on the `{coin}-updown-…`
   pattern). This is shared state that survives restarts and is consistent across
   multiple scan workers. The gate now caps on `max(in-memory window, DB count)`,
   so it can never under-count after a restart.
2. **Default cap → 1** (owner directive 2026-06-10): treat BTC/ETH/SOL as a
   single correlated bet — take the best one per direction, skip the rest. The
   cluster can no longer stop out together at all. Still tunable via
   `CORRELATED_MAJORS_SAME_DIR_LIMIT` (2 = old behaviour, 0 = disabled).

## 2. Current system architecture

```
_process_candidate (step 3d-ii, per candidate, sequential per user):
  _maj_asset = _major_asset_from_candidate(cand)        # BTC/ETH/SOL or None
  if _maj_asset:
     open = await _open_correlated_majors_count(user, side)   # DB, fail-soft → 0
  _gate_correlated_majors(..., open_position_count=open):
     effective = max(window_count, open)                # window survives the gap
                                                         # between accept & commit
     if effective >= limit:  skip "…concentration"
  ... on accepted entry → _correlated_majors_record_entry(window)   # unchanged
```

`_open_correlated_majors_count` is fail-soft: any DB error logs
`open_correlated_majors_count_failed` and returns 0, so a transient DB fault
falls back to the in-memory window and never blocks trading on its own fault
(mirrors the existing `open_position_market_check_failed` posture).

## 3. Files created / modified (repo-root paths)

- `projects/polymarket/crusaderbot/config.py` — `CORRELATED_MAJORS_SAME_DIR_LIMIT` default 2 → 1; comment rewritten (now-authoritative DB count + owner directive).
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` — new `_open_correlated_majors_count`; `_gate_correlated_majors` gains `open_position_count` and caps on `max(window, open)`; call site awaits the DB count for cluster majors.
- `projects/polymarket/crusaderbot/tests/test_correlated_majors_limit.py` — default-cap test → 1; `_run` stubs `_open_correlated_majors_count`; 5 new tests (default-1 block, empty-window/DB-count block = restart case, cap-2 DB path, opposite-side isolation, pure-gate max-of-sources).
- `projects/polymarket/crusaderbot/reports/forge/correlated-majors-db-cap.md` — this report.
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `state/CHANGELOG.md` — sync.

## 4. What is working

- 29/29 correlated-majors tests pass (24 inherited + 5 new); 210 passed across safe_close / correlated / signal_scan / risk_gate regression; ruff clean on all touched files.
- DB-count path proven to enforce the cap with an empty in-memory window (the restart scenario) and to isolate opposite sides.
- Default cap of 1 verified at config load and end-to-end (2nd same-direction major blocked).

## 5. Known issues

- **Identical P&L is NOT a bug.** Verified in `domain/execution/paper.py:115` + `exit_watcher.py:486-507`: a paper SL exit fills at the capped stop price `entry×(1−sl_pct)`, so realised loss = `−sl_pct × size`. Equal Kelly sizing across the three majors → identical loss, with different *displayed* exit prices (different entries). Correct by design; left unchanged.
- The in-memory window remains as a fast complement (catches the sub-second gap between a same-tick accept and the position-row commit). It is no longer the sole source, so its volatility is no longer a correctness risk.
- `_open_correlated_majors_count` adds one indexed DB read per cluster-major candidate (only BTC/ETH/SOL), consistent with the existing per-candidate `_has_open_position_for_*` reads.

## 6. What is next

- WARP🔹CMD review; Fly CD deploys on merge to main. No runtime flip needed (default 1 active on deploy).
- Optional: if the owner later wants 2 correlated majors, set `CORRELATED_MAJORS_SAME_DIR_LIMIT=2` in Fly — no redeploy-sensitive code path involved now.
