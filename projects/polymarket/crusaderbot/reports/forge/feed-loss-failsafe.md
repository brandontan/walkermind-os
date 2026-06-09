# WARP-76 H3 — RTDS oracle feed-loss fail-safe

Branch: WARP/feed-loss-failsafe
Role: WARP•R00T (executing as build/fix)
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: feed-drop → scan halts + operator alert; reconnect → scan resumes + operator alert; oracle_edge_status='feed_down' on a down feed.
Not in Scope: ENABLE_LIVE_TRADING / USE_REAL_CLOB / live exec path / domain/risk/gate.py / domain/execution/paper.py / DB schema / migrations. No new dependency.
Suggested Next Step: WARP🔹CMD review + merge, then proceed to WARP-76 H4 (multi-user isolation audit, branch WARP/isolation-audit).

## Tier decision (recorded)

The H3 task carried a stop-condition: escalate to MAJOR + SENTINEL if the scan
halt touches the execution path. A read-only audit confirmed it does **NOT**:
`oracle_edge_status` is read only in the signal/scoring layer
(`domain/strategy/scorer.py:oracle_denied`), never in `domain/risk/gate.py` or
`domain/execution/paper.py` (grep: zero matches). The halt gate lives entirely
in `services/signal_scan/signal_scan_job.run_once` before market evaluation.
**Tier stays STANDARD** — no execution-path change, no escalation needed.

## 1. What was built

A protective fail-safe for the RTDS Chainlink oracle WebSocket. Previously, if
the feed went silent the per-symbol staleness drop (`ORACLE_STALENESS_SEC=10s`)
suppressed a single edge but the scan kept iterating with no operator
visibility. H3 adds a distinct, longer "the stream is DOWN" threshold that halts
evaluation and pages the operator, auto-resuming on recovery.

1. **Config** — `ORACLE_FEED_TIMEOUT_SEC: int = 120` with a strictly-positive
   `@field_validator` (mirrors the existing interval validators).
2. **Oracle liveness** — `PolymarketRTDSOracle.latest_tick_age_sec()` and
   `is_feed_down(timeout_sec)`. "Down" fires only for a feed that delivered
   ticks then went silent past the timeout; a cold start with no tick yet is
   **not** "down" (warming up), so the scan is never frozen before the first
   tick.
3. **Status propagation** — `OracleEdgeConfig.feed_down_provider` (bound to
   `oracle.is_feed_down(ORACLE_FEED_TIMEOUT_SEC)`); `_observe_oracle_edge`
   returns `oracle_edge_status='feed_down'` (instead of `warming_up`) when the
   provider reports down, so a dropped stream is distinguishable in telemetry.
4. **Scan halt gate + alerts** — `_oracle_feed_halts_scan()` runs at the top of
   `run_once` (after the disabled-strategy refresh, before any evaluation):
   - feed down → return early (no new market evaluation) + log
     `scan_outcome=skipped_oracle_feed_down`;
   - pages the operator **once** per transition:
     "🚨 RTDS feed lost — scan halted" on down,
     "✅ RTDS feed restored — scan resumed" on the first tick after recovery
     (a latch prevents re-paging every tick);
   - no-op unless `ORACLE_ENABLED`; fully fail-soft (any error → returns False
     → scan proceeds, so a monitoring fault can never freeze trading, and the
     per-evaluation staleness guards still protect against stale data).

Protective only: the gate halts evaluation and never opens a permissive path or
bypasses a gate.

## 2. Current system architecture

```
RTDS WS ──ticks──> PolymarketRTDSOracle._ticks (monotonic-stamped)
                         │
   run_once() ──> _oracle_feed_halts_scan()  (ORACLE_ENABLED only)
                         │ is_feed_down(ORACLE_FEED_TIMEOUT_SEC)
            down ────────┴──────── up
        halt + page once       resume + page once
        (return early)         (continue normal scan)

late_entry_v3._observe_oracle_edge():
   feed_down_provider() True ─> oracle_edge_status='feed_down'
```

### Alert text

```
🚨 RTDS feed lost — scan halted
No oracle tick within ORACLE_FEED_TIMEOUT_SEC; new market evaluation is paused until the feed recovers.

✅ RTDS feed restored — scan resumed
Oracle ticks are fresh again; market evaluation has resumed.
```

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/tests/test_warp76_feed_loss.py`

Modified:
- `projects/polymarket/crusaderbot/config.py` (ORACLE_FEED_TIMEOUT_SEC + validator)
- `projects/polymarket/crusaderbot/domain/strategy/oracle/rtds.py` (latest_tick_age_sec + is_feed_down)
- `projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py` (OracleEdgeConfig.feed_down_provider + feed_down status branch)
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` (feed gate + alerts + latch; wire feed_down_provider)

No change to ENABLE_LIVE_TRADING / USE_REAL_CLOB / gate.py / paper.py / live exec path / schema.

## 4. What is working

- `tests/test_warp76_feed_loss.py`: **11 passed** (full deps):
  - config default 120 + rejects 0/negative;
  - `is_feed_down` False before first tick, True after silence > timeout, False after a fresh tick;
  - `_observe_oracle_edge` → `feed_down` when down, `warming_up` when up-but-no-price;
  - scan gate halts + pages "lost"; recovery resumes + pages "restored"; no-op when ORACLE_ENABLED False; pages only once until recovery.
- Regression: `test_oracle_rtds.py`, `test_oracle_edge_wiring.py`, `test_config_defaults.py`, `test_signal_scan_job.py` → **126 passed**.
- `ruff check` (project config) on all changed files: clean.

## 5. Known issues

- "Feed down" requires at least one prior tick (by design — matches the spec's
  "last tick age > timeout" semantics). A feed that NEVER connects produces no
  ticks → not flagged "down"; that path is already safe because every
  evaluation returns `warming_up` (no oracle edge computed, no trade on stale
  data). A never-connecting feed is an `ORACLE_ENABLED` misconfiguration, out of
  scope for this fail-safe.
- The halt is process-wide for the scan tick when ORACLE_ENABLED; oracle is
  currently OFF by default, so this is inert until an operator enables it.

## 6. What is next

- WARP🔹CMD review + merge of WARP/feed-loss-failsafe.
- Proceed to WARP-76 H4 — multi-user isolation audit (branch WARP/isolation-audit).
