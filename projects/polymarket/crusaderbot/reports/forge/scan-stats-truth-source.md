# WARP•FORGE Report — Scan-Stats Truth-Source

- Branch: `WARP/scan-stats-truth-source` (harness-assigned working branch: `claude/crusaderbot-signal-scan-debug-Xnckj`)
- Validation Tier: **STANDARD** (user-facing observability; no trading-safety / risk / execution code touched)
- Claim Level: **NARROW INTEGRATION** (code + unit/DB-evidence validated; full live-runtime proof requires Fly deploy)
- Validation Target: operator `/panel → Stats` now reflects the real feed-eval engine (`scan_runs`) and surfaces the true conversion blockers; legacy `run_signal_scan` no longer masquerades as the canonical `signal_scan` telemetry
- Not in Scope: throughput tuning (`MAX_CONCURRENT_TRADES`, `_MAX_SIGNAL_AGE_SECONDS`), retiring `run_signal_scan`/`copy_trade`, stale resolved-position redemption, edge-model bug #1
- Suggested Next Step: WARP🔹CMD review → merge → Fly.io redeploy → open `/panel → Stats` and confirm non-zero candidate counts + the rejection-breakdown line

---

## 1. What was built

A telemetry truth-source fix. The beta report ("bot finds 0 candidates / only ~5 trades a week") was traced **not** to a scan defect but to the operator dashboard reading the wrong data source.

Two scan jobs are scheduled at `SIGNAL_SCAN_INTERVAL` (`scheduler.py:786` and `:789`):

| Job | Writes to | Observed per tick |
| --- | --- | --- |
| Legacy `run_signal_scan` (`scheduler.py`, `_strategies={"copy_trade"}`) | `job_runs` (`job_name=signal_scan`) | `markets_seen=0`, `candidates_emitted=0`, `strategies_loaded=["copy_trade"]` |
| Real `sf_scan_job.run_once` (feed-eval + lib + confluence) | `scan_runs` | `strategies_loaded=11`, `markets_seen=100`, `candidates_emitted≈453` (climbing) |

The Telegram operator panel `/panel → Stats` read the **legacy** `job_runs` row, so a healthy engine looked dead. The fix repoints the panel at `scan_runs` (the real engine, as `api/admin.py /scan/last` already does), surfaces the true conversion blockers, and renames the legacy job so its `job_runs` rows stop masquerading as `signal_scan`.

Disproved handoff hypotheses (live-DB evidence): `capital_alloc_pct` (balanced user balance $944.86 × strategy weight 0.1 → size $10, passes the $1 floor), `category_filters` (`_build_market_filters` hardcodes `categories=[]`), PR #1298 (already merged in HEAD `e235fa2`). #1312 is verified working — the balanced user re-entered 5 diverse short-term positions at 00:27 UTC (Strait of Hormuz 6.9d, Knicks/Cavs, US-Iran deals 1.9–6.9d), no 2026/2028 futures.

The real (out-of-scope) limiter: all 5 users sit at `MAX_CONCURRENT_TRADES=5`, so candidates reaching the risk gate are rejected at `step_7_max_concurrent_trades`; `skipped_signal_stale` drops signals older than 30 min (`314/453` in the latest tick).

## 2. Current system architecture

```
scheduler (interval = SIGNAL_SCAN_INTERVAL)
├── run_signal_scan ............. legacy, copy_trade-only → job_runs[legacy_copy_trade_scan]   (observational only)
└── sf_scan_job.run_once ........ REAL engine (lib + confluence + signal-feed) → scan_runs

scan_runs ──(fetch_latest_scan_run)──► operator_panel /panel → Stats   [NEW path]
scan_runs ──(GET /scan/last)─────────► api/admin.py                    [existing]
```

`fetch_latest_scan_run()` mirrors the column set served by `api/admin.py /scan/last`; `_render_stats` maps the `scan_runs` fields and a new `_summarize_breakdown()` renders the top buckets of `rejection_breakdown` / `skip_breakdown` so the operator sees *why* candidates don't convert.

## 3. Files created / modified

- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` — added `async def fetch_latest_scan_run() -> dict[str, Any] | None` (latest `scan_runs` row; try/except → `None`, logs `scan_run_fetch_latest_failed`, no silent failure)
- `projects/polymarket/crusaderbot/bot/handlers/operator_panel.py` — `/panel → Stats` repointed from `job_tracker.fetch_latest("signal_scan")` to `fetch_latest_scan_run()`; `_render_stats` remapped to `scan_runs` fields (int `strategies_loaded`, `users_evaluated`, `positions_created`, `paper_orders_created`); added `_summarize_breakdown()`; module docstring + Help text updated
- `projects/polymarket/crusaderbot/scheduler.py` — legacy job id `"signal_scan"` → `"legacy_copy_trade_scan"`; `SignalScanMetrics` + `run_signal_scan` docstrings note the panel now reads `scan_runs`
- `projects/polymarket/crusaderbot/tests/test_signal_scan_job.py` — 3 new tests for `fetch_latest_scan_run` (dict / None / error-swallow)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `state/CHANGELOG.md` — state sync (this lane)

## 4. What is working

- `_render_stats` renders the real engine: `Candidates emitted: 453`, `Risk rejections: step_7_max_concurrent_trades: 33`, `Skips: skipped_signal_stale: 314, skipped_open_position_exists: 101` (verified standalone)
- `48/48` tests pass in `tests/test_signal_scan_job.py` (45 existing + 3 new)
- `py_compile` clean on all three modified production files
- Live-DB evidence confirms the diagnosis (`scan_runs` candidates_emitted 410→453 across recent ticks; `job_runs` legacy rows flat at 0)

## 5. Known issues

- Real throughput is capped: all 5 users hold 5 open positions (`MAX_CONCURRENT=5`); 314/453 candidates are skipped stale (>30 min). Raising the cap / relaxing staleness is a **separate MAJOR lane** (risk core → SENTINEL + owner-supplied numbers)
- Two balanced-user open positions are past `resolution_at` but still `open` (redemption / exit-watcher lag) — separate lane
- Legacy `run_signal_scan` / `copy_trade` still runs (now relabelled). Whether to retire it entirely (two execution paths both call `router_execute`) is an architecture decision for WARP🔹CMD
- Branch `claude/crusaderbot-signal-scan-debug-Xnckj` violates the `WARP/{feature}` rule; harness pre-assigned it — flagged to WARP🔹CMD

## 6. What is next

1. WARP🔹CMD review (STANDARD) → merge → Fly.io redeploy
2. Post-deploy: open `/panel → Stats`, confirm non-zero candidates + the rejection-breakdown line
3. Decide the three follow-up lanes: throughput tuning (MAJOR), stale-position redemption, legacy-scan retirement
