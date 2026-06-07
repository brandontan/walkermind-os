# WARP-78 — 15m paper_real accrual stall: investigation (REPORT ONLY)

- Role: WARP•R00T
- Validation Tier: MINOR (read-only investigation; no code, no runtime change).
- Claim Level: FOUNDATION (root-cause analysis from DB evidence).
- Validation Target: why the `BTC/15m` + `ETH/15m` `paper_real` cells stalled
  far below the Track C ≥200/cell sample minimum, blocking the 4-cell cutover.
- Not in Scope: any fix (this is a CMD-reviewed findings report); the 5m cells
  (healthy); the `--from-db` re-run (CMD-gated, data not ready).
- Branch: `WARP/15m-accrual-investigation`
- Method: 4 read-only SQL queries against the CrusaderBot Supabase
  (`ykyagjdeqcgcktnpdhes`). No writes.

---

## 1. Problem

The real-data re-run readiness check found the 15m cells stuck far below the
Track C §1.5 minimum (≥200 settled/cell):

| Cell | `paper_real` settled (open→close) | latest 15m observation |
|---|---|---|
| BTC/15m | 13 | first_seen 13:57 UTC / settled 14:30 UTC |
| ETH/15m | 11 | first_seen 13:57 UTC / settled 14:30 UTC |
| BTC/5m | 77→ (live, ~7.8/h) | first_seen 18:0x UTC (current) |
| ETH/5m | 75→ (live, ~7.6/h) | first_seen 18:0x UTC (current) |

5m accrues normally; 15m produced **zero** new rows for ~4h while 5m ran full.

## 2. Evidence

### 2.1 Hourly observation cadence (paper_real, 2026-06-06 UTC)

| Hour | 5m observed | 15m observed |
|---|--:|--:|
| 06:00 | 12 | 4 |
| 07:00 | 24 | 5 |
| 08:00 | 24 | 8 |
| 09:00 | 23 | 5 |
| 10:00 | 23 | 8 |
| **11:00** | **2** | **0** |
| **12:00** | **0** | **0** |
| 13:00 | 6 | 2 |
| 14:00 | 24 | 0 |
| 15:00–18:00 | 24/h | 0 |

Two distinct events: (a) a **system-wide dip ~11:00–13:00** hitting BOTH
timeframes (a transient restart/outage); (b) after ~13:00 **5m fully recovered
(24/h) but 15m never resumed (0/h)**.

The shadow writes a `factor_vector` for *every evaluated candle* (traded or not),
so 0 rows ⇒ no 15m candles were **evaluated** post-13:00 — i.e. there were no
15m markets to scan. This is NOT entry starvation (which would still write rows).

### 2.2 Market availability (`markets` table, slug `*-updown-(5m|15m)-*`)

| series | markets | last_synced | latest_resolution | markets resolving in the future |
|---|--:|---|---|--:|
| 5m | 14,474 | 18:10 UTC (live) | 18:20 UTC | **4** |
| 15m | 1,079 | **14:04 UTC** | **14:30 UTC** | **0** |

- **No `updown-15m` market resolves after 14:30 UTC.** The 878 still-`active`
  15m rows are all past-due (frozen at the 14:04 sync; the feed stopped
  returning them before the bot could mark them resolved).
- 5m has live future markets and is syncing every cycle.

## 3. Root cause

**External: Polymarket stopped offering the `updown-15m` crypto up/down series
at ~14:30 UTC.** With no 15m markets in the feed, there are no 15m candles to
discover/evaluate → zero 15m `factor_vectors` → the "stall." This is a venue
product change, **not a CrusaderBot defect** — the bot correctly syncs and
evaluates whatever the venue offers, and the 5m series is unaffected.

The ~11:00–13:00 dip is a *separate* transient that hit both timeframes and
fully recovered for 5m; it is not the cause of the 15m stall (15m markets were
still syncing until 14:04, after that window).

## 4. Risk + technical impact

- Risk: **MEDIUM** — blocks the 15m portion of the cutover decision. NO capital
  or safety risk: paper mode, and with no 15m markets there is no 15m trading to
  protect regardless.
- Impact: `BTC/15m` + `ETH/15m` **cannot reach** the ≥200/cell minimum — the
  count (13/11) is effectively terminal unless Polymarket reinstates the series.
  A **4-cell** Track C verdict is therefore unattainable. `candle_auto`+`auto`
  users on a 15m timeframe have no markets to route anyway.

## 5. Recommended solution (CMD decides scope)

1. **Scope the cutover to 5m-first** — `BTC/5m` + `ETH/5m` only (CMD's
   pre-identified per-cell option). The locked C2 +0.015 margin and the §1.7
   verdict logic are unchanged; only the cell set narrows from 4 to 2 (apply
   §1.5 minimums + the per-cell catastrophic gate to the two 5m cells; the
   "overall" aggregates those two). 5m reaches ≥200/cell in ~16–17h.
2. **Drop 15m from the cutover** until/unless the venue reinstates the series.
   Add a lightweight watch: alert if any `slug ~ 'updown-15m'` market has
   `resolution_at >= now()` again, then re-evaluate 15m inclusion.
3. (Ops awareness, no action) The ~11:00–13:00 observation dip — confirm whether
   it correlates with a deploy/restart; 5m recovered, so no lingering issue.
4. (Hygiene, separate lane, optional) 878 stale `active` 15m markets are frozen
   past their resolution; a cleanup could mark them resolved/expired so they
   don't linger as `active`. Low priority, out of scope here.

## 6. Files affected / validation

- Files changed: **none** (report-only) + state sync.
- Validation: 4 read-only SQL queries (cadence histogram; per-cell paper_real
  counts; 15m vs 5m market sync recency; future-resolution check). No writes,
  no `factor_vectors` mutation, no prod behavior change.

Suggested Next Step: WARP🔹CMD reviews → confirm **5m-first** cutover scope (or
hold for 15m). Then, once 5m ≥200/cell and PR #1670 (data_source filter) is
merged: `ev_comparator --from-db` → `report_cutover_holdout --from-db
--margin 0.015` on the 5m cells → §1.7 verdict → cutover decision.
