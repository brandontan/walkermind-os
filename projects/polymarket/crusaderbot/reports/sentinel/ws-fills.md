# WARP•SENTINEL REPORT — ws-fills

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Audited Branch: WARP/CRUSADERBOT-PHASE4D-WEBSOCKET-FILLS
Audited HEAD: 8197373f60065187271f6098352fbe91900a27d1
Source: projects/polymarket/crusaderbot/reports/forge/ws-fills.md
Audit Date: 2026-05-09 21:15 Asia/Jakarta

---

## HEAD DEVIATION (must read first)

WARP🔹CMD dispatch instructed re-audit at HEAD `0d0ce97`. PR HEAD has
since advanced to `8197373` (4 additional commits: round-9 `8a6413b` +
`ce090c3`, round-10 `0ddb284` + `b52d0fc`, round-11 `1f77598` +
`8197373`). Auditing `0d0ce97` strictly would miss Codex P1/P2 fixes
landed AFTER that commit and produce findings that are already
resolved in the actual PR head. Audit therefore targets the PR HEAD
`8197373` — explicitly noted here for the audit trail. CI is GREEN on
`8197373` (verified via `pull_request_read.get_check_runs`).

---

## TEST PLAN

Phases executed (dev-scope: validate code correctness; no infra
deployment in this PR):

* Phase 0 — Pre-test gate (forge report path/sections, PROJECT_STATE
  update, domain structure, implementation evidence).
* Phase 1 — Functional testing per module (ws.py, ws_handler.py,
  lifecycle.py WS handlers, scheduler integration).
* Phase 2 — Pipeline end-to-end placement (DATA → … → LIFECYCLE).
* Phase 3 — Failure modes (disconnect / parser drop / partial fill /
  cancel-without-size_matched / WS-gap aggregate / status race-loss).
* Phase 4 — Async safety (asyncio only, no threading; single
  transaction per terminal step).
* Phase 5 — Risk rules in code (Kelly=0.25, ENABLE_LIVE_TRADING guard,
  USE_REAL_CLOB paper bail).
* Phase 6 — Latency (WS push vs 30s polling fallback).
* Phase 7 — Infra (no new schema; existing migration 015 sufficient;
  Redis / PostgreSQL untouched).
* Phase 8 — Telegram (deferred to terminal path; partial fills do not
  notify).

Environment: dev validation; activation posture preserved (paper-only
default). No live socket opened during audit.

---

## FINDINGS

### Phase 0 — Pre-test gate

* PASS — Forge report at `projects/polymarket/crusaderbot/reports/forge/ws-fills.md`,
  all 6 mandatory sections present + Validation Tier / Claim Level /
  Validation Target / Not in Scope / Suggested Next Step metadata.
* PASS — `state/PROJECT_STATE.md` updated (Phase 4D delivery entry +
  NEXT PRIORITY entry both present, line 21 + line 30).
* PASS — No `phase*/` folders in repo (`find . -type d -name 'phase*'`
  empty).
* PASS — Implementation files exist: `integrations/clob/ws.py:1-300+`,
  `integrations/clob/ws_handler.py:1-360`,
  `domain/execution/lifecycle.py:533-810` (WS surface),
  `scheduler.py` (ws_connect / ws_watchdog / ws_shutdown jobs),
  `main.py` lifespan teardown.

### Phase 1 — Functional

* PASS — `ws_handler.parse_message` correctly fans out 5 event types:
  `user_fill` / `trade` / `user_order` / `order` / channel chatter.
  Evidence: `tests/test_clob_ws_handler.py` 25/25 green.
* PASS — `_normalise_fill` (ws_handler.py:129-250) emits per-maker
  events from `maker_orders[].order_id` + a deduped taker event (Codex
  P1 round-3 fix at `8aa7a90`); regression test
  `test_user_fill_maker_orders_emits_one_event_per_maker`.
* PASS — `_TRADE_STATUS_SETTLED` allow-list (ws_handler.py:98-126)
  rejects MATCHED/MINED/RETRYING/FAILED, accepts CONFIRMED-only.
  Parametrised regression `test_trade_frame_with_non_settled_status_emits_no_fill`
  covers MATCHED / MINED / RETRYING / FAILED / rejected / cancelled.
* PASS — `_normalise_order_update` (ws_handler.py:253-299) derives
  `filled` from `original_size == size_matched` for `type:UPDATE`
  frames without explicit status (Codex P2 round-9 fix at `8a6413b`);
  partial UPDATEs and zero-matched UPDATEs stay `open`.
  Tests `test_order_update_fully_matched_routes_to_filled` /
  `test_order_update_partial_match_stays_open` /
  `test_order_update_zero_size_matched_stays_open`.
* PASS — `normalise_status` (ws_handler.py:56-72) maps
  `ORDER_STATUS_*` prefix-stripped + `cancel*` prefix-matched
  (Codex P1 round-5 fix at `c96e5bd` — pinned by
  `test_order_event_with_cancellation_type_maps_to_cancelled`).
* PASS — `handle_ws_fill` (lifecycle.py:640-725) is records-only:
  inserts the per-trade row + bumps `positions.current_price`; does
  NOT mark the order terminal (Codex P1 round-1 fix at `8c783b5` /
  CMD-ratified). Pinned by
  `test_ws_fill_records_partial_only_no_terminal_update` and
  `test_ws_partial_fills_accumulate_without_terminating`.
* PASS — `handle_ws_order_update` (lifecycle.py:727-809) dispatches
  on `filled` / `cancelled` / `expired` and persists the matched
  aggregate from `open` partial UPDATE frames (Codex P1 round-10 fix
  at `0ddb284`).

### Phase 2 — Pipeline placement

* PASS — WS path lands in LIFECYCLE stage per the locked
  `DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING`
  order. WS handlers do NOT bypass RISK; they only react to settled
  fills on orders that already passed `domain/execution/live.execute`
  with the full guard chain.

### Phase 3 — Failure modes

* PASS — WS disconnect: exponential backoff with ±25% jitter, capped
  at `WS_RECONNECT_MAX_DELAY_SECONDS=60`; attempt counter resets on
  successful open (`tests/test_clob_ws.py::test_backoff_caps_at_max`,
  `test_backoff_grows_exponentially_with_jitter`).
* PASS — Heartbeat-driven recycle: missed pong past
  `interval + timeout` closes socket (`test_heartbeat_timeout_recycles_socket`).
* PASS — Parser error containment: malformed JSON / non-numeric
  price-size / missing ids drop silently, log at WARNING; loop never
  crashes (`test_unknown_frame_does_not_crash_loop`).
* PASS — Dispatcher exception containment: a raising callback does
  not stop subsequent fills (`test_dispatcher_exception_is_contained`).
* PASS — Partial-fill cancel without `size_matched`: hydrates from
  `_load_existing_fills` so `_terminal_close` refunds only the
  unmatched remainder (Codex P1 round-7 fix at `954a301`). Test
  `test_ws_cancel_after_partial_ws_fill_hydrates_prior_fills`.
* PASS — WS-gap aggregate undercover: when WS captured one trade=50
  and broker aggregate=200, hydration picks the LARGER agg figure so
  refund math is not understated (Codex P1 round-11 fix at
  `1f77598`). Test `test_cancel_uses_larger_agg_when_per_trade_undercovers`.
* PASS — Aggregate dedup contract: `_record_fills_in_conn`
  (lifecycle.py:533-624) compares per-trade SUM to incoming agg.size;
  skips agg only when per-trade SUM ≥ agg (Codex P2 round-8 fix at
  `8e73682`). Test `test_ws_fill_then_order_update_filled_skips_aggregate_row`
  + `test_ws_gap_aggregate_fill_inserted_when_per_trade_undercovers`.
* PASS — UPSERT for size growth: agg-* rows refresh on subsequent
  partial UPDATEs (`ON CONFLICT (fill_id) DO UPDATE SET size, price`).
  Per-trade rows are unique per match — UPSERT is a no-op for
  duplicates.
* PASS — WS+poll race: `UPDATE orders ... RETURNING id` race-loss is
  exercised in both `_on_fill` and `_terminal_close`; second writer
  bails with no side effects (`test_ws_then_poll_dedup_via_fill_id_unique_constraint`).

### Phase 4 — Async safety

* PASS — `asyncio` only; no `threading` import in any touched file
  (`grep -n 'import threading' integrations/clob/ws.py
  integrations/clob/ws_handler.py domain/execution/lifecycle.py
  scheduler.py main.py` returns empty).
* PASS — DB writes are wrapped in `conn.transaction()` blocks
  (lifecycle.py:248-288 / 394-457 / 706-725 / 802-809). The
  open-status partial UPDATE persistence path (lifecycle.py:802-809)
  uses the same transaction shape so per-trade and agg writes share
  isolation guarantees.
* PASS — Heartbeat / read / run loops use `asyncio.wait_for` with
  explicit timeouts; stop signal cancels all three cleanly
  (`test_stop_during_backoff_exits_clean`).
* PASS — Singleton `_ws_client` is module-level state in `scheduler.py`;
  watchdog tears it down + reconstructs without leaking the prior
  client's tasks (`test_ws_watchdog_reconnects_when_client_not_alive`).

### Phase 5 — Risk rules in code

* PASS — Kelly fraction `a = 0.25` preserved (this PR does not touch
  `domain/risk/`). Verified via `grep -n 'kelly' domain/risk/` — no
  changes.
* PASS — `ENABLE_LIVE_TRADING` is NOT read by the WS surface (no
  occurrences of the symbol in `ws.py`, `ws_handler.py`,
  `lifecycle.py` WS handlers, or `scheduler.py` ws_*). Activation
  posture preserved.
* PASS — `USE_REAL_CLOB` paper-mode hard guard: `ws.py
  ClobWebSocketClient.start()` returns early when False; the
  injected `connect_factory` is NEVER called in that branch
  (`test_paper_mode_start_is_noop_and_factory_never_called`).
* PASS — Order-creation guards (position size / loss limit / drawdown
  / liquidity / dedup / kill switch) are not bypassed: WS path only
  observes already-placed orders and updates terminal state. New
  orders still flow through `domain/execution/live.execute` with the
  full guard chain.

### Phase 6 — Latency

* PASS — WS push path is structurally sub-second: parser is pure
  function (no I/O); `handle_ws_fill` issues 1 INSERT + 1 UPDATE per
  event (single round-trip each, in one transaction). The 30s
  polling fallback remains as a safety net but is no longer the
  primary fill discovery channel.
* PASS — No new blocking calls; no `time.sleep`; all sleeps are
  `await asyncio.sleep`.

### Phase 7 — Infra

* PASS — No new database migrations. The `fills` table from
  migration 015 is sufficient (existing unique fill_id index
  supports the UPSERT contract).
* PASS — No Redis / InfluxDB writes added.
* PASS — `pyproject.toml` adds `websockets>=12.0,<14.0`; lazy import
  inside `ws._open_connection` keeps unit tests soft on the
  dependency.
* PASS — Singleton `_ws_client` in `scheduler.py` lives for the
  process lifetime; `ws_shutdown` is wired to FastAPI lifespan
  teardown in `main.py`. Forge report flags non-FastAPI entry points
  as a known consideration (acceptable for current deployment shape).

### Phase 8 — Telegram

* PASS — `handle_ws_fill` does NOT call `_safe_notify_user` (the
  records-only contract defers all user-facing messages to the
  terminal path). A multi-trade GTC partial fill therefore does NOT
  spam the user with N "Order filled" alerts.
* PASS — Terminal close (`_terminal_close`) emits one user-facing
  Telegram message per terminal transition, with the partial-fill
  refund context appended when applicable (lifecycle.py:471-482).
* PASS — Operator alert surface preserved: `_mark_stale` paging
  (lifecycle.py:509-518) is unchanged.

---

## CRITICAL ISSUES

None found.

---

## STABILITY SCORE

| Dimension | Weight | Score | Notes |
|---|---:|---:|---|
| Architecture | 20 | 19 | Clean separation (transport / parser / handlers); UPSERT semantics carefully chosen; hydration prefers larger of per-trade vs agg. -1 for the docstring drift on `_record_fills_in_conn` line 557 still saying "polling-only path; insert as before" after the round-10 UPSERT switch — cosmetic only. |
| Functional | 20 | 20 | All 11 Codex review rounds addressed with regression tests. All 5 GATE-mandated tests present + passing. 111 WS-specific tests + 726/726 hermetic suite green. |
| Failure modes | 20 | 19 | Backoff+jitter, watchdog, heartbeat-recycle, parser error containment, dispatcher exception containment, race-loss dedup, hydration-on-cancel, agg-undercover hydration. -1: auth-rejection edge case is documented in forge §5 but not pinned by an integration test (acceptable; needs Polymarket sandbox creds). |
| Risk rules | 20 | 20 | WS path is observation-only. Activation guards untouched. Paper-mode hard guard verified by injected-asserting factory. |
| Infra + Telegram | 10 | 10 | No new schema. Migration 015 sufficient. Telegram correctly deferred to terminal path. |
| Latency | 10 | 10 | WS push is sub-second; pure-function parser; single-roundtrip writes; no blocking calls. |
| **Total** | **100** | **98** | |

---

## GO-LIVE STATUS

**APPROVED — 98/100, 0 critical issues.**

Reasoning: every Codex P1/P2 finding (rounds 1-11) is addressed with
in-tree code changes AND regression tests. Activation posture is
strictly preserved (paper-only default, ENABLE_LIVE_TRADING never
read by the WS surface). Dual-source dedup with the polling fallback
is sound: per-trade fill_id uniqueness, agg-* UPSERT for size growth,
hydration that prefers the larger of per-trade SUM vs agg.size on
cancel/expiry. CI is green on `8197373`.

---

## FIX RECOMMENDATIONS

Priority-ordered (all non-blocking):

1. **MINOR — docstring drift in `_record_fills_in_conn`** (lifecycle.py:557).
   The "* no per-trade rows — polling-only path; insert as before"
   bullet predates the round-10 UPSERT switch. Update to reflect the
   "ON CONFLICT DO UPDATE" reality. Cosmetic only — does not affect
   runtime behaviour.

2. **MINOR — auth-rejection integration test gap.** Forge §5 already
   flags this. Once a Polymarket sandbox auth pair is provisioned,
   add a hermetic test that asserts a rejected-auth `close` is
   treated as a normal disconnect (no special "auth failed" alert
   path raises). Track as follow-up — does not block this PR.

3. **OBSERVABILITY — no current_price snapshot on terminal close.**
   `handle_ws_fill` bumps `positions.current_price` per-trade
   (lifecycle.py:717-725), but terminal close does not write a final
   mark-price snapshot. Acceptable because the UPDATE is harmless
   when no position row exists; flagging as future enhancement.

4. **DEFERRED — `WARP/CRUSADERBOT-WS-MARKET-DATA`** for per-market
   `book` / `price_change` subscription (Forge §6). Not in scope of
   this lane; track as a separate post-merge follow-up if intra-tick
   signal generation needs push-based ticks.

---

## TELEGRAM PREVIEW

The WS surface itself does not introduce new Telegram messages.
Existing terminal-close formatting is preserved verbatim from
Phase 4C, with the partial-fill refund context auto-appended:

**Order filled** (terminal path, polling OR ws_order_update.filled):

```
✅ *Order filled*
Market `mkt-{condition_id}`
*YES* 100.0000 @ 0.550
```

**Order cancelled (full)** (no fills hydrated):

```
❌ *Order cancelled*
Market `mkt-{condition_id}`
*YES* size $100.00
```

**Order cancelled (partial fill — round-7 / round-10 hydration)**:

```
❌ *Order cancelled*
Market `mkt-{condition_id}`
*YES* size $100.00
Filled `$25.00` / refunded `$75.00`
```

**Order expired** identical shape with the ⌛️ glyph.

**Stale-order operator alert** (paged, unchanged):

```
⚠️ *STALE ORDER*
order_id=`{uuid}` user=`{uuid}`
market=`mkt-{condition_id}` attempts=`48`
reason: `max poll attempts reached (broker_status=open)`
Reconcile via Polymarket dashboard.
```

Operator commands unchanged: `/kill`, `/resume`, `/ops_dashboard`,
`/about`, `/status`, `/demo`. WS path is opt-in via `USE_REAL_CLOB=True`
+ implicit at-runtime via the `ws_watchdog` job — no new operator-
facing toggles.

---

## EVIDENCE INDEX

| Round | Codex thread | Fix commit | Regression test |
|---|---|---|---|
| P1 round 1 | `r3213035734` (records-only) | `8c783b5` | `test_ws_fill_records_partial_only_no_terminal_update` |
| P1 round 1 | `r3213035720` (WS URL `/ws/user`) | `542afb1` | `test_start_opens_socket_and_sends_subscribe_with_auth` |
| P1 round 1 | `r3213035724` (subscribe shape) | `7b120b7` | same test asserts payload |
| P1 round 1 | `r3213035729` (heartbeat 10s) | `8aa7a90` + `542afb1` | `test_heartbeat_pong_keeps_socket_alive`, `test_heartbeat_timeout_recycles_socket` |
| P1 round 1 | `r3213057448` (maker_orders[]) | `8aa7a90` | `test_user_fill_maker_orders_emits_one_event_per_maker` |
| P1 round 4 | `r3213163058` (CONFIRMED allow-list) | `f1e4efb` | `test_trade_frame_with_non_settled_status_emits_no_fill` (param) |
| P1 round 5 | `r3213179479` (CANCELLATION) | `c96e5bd` | `test_order_event_with_cancellation_type_maps_to_cancelled` |
| P1 round 7 | `r3213200463` (cancel hydration) | `954a301` | `test_ws_cancel_after_partial_ws_fill_hydrates_prior_fills` |
| P2 round 6 | `r3213190778` (agg dedup) | `df6722b` | `test_ws_fill_then_order_update_filled_skips_aggregate_row` |
| P2 round 8 | `r3213211341` (size-comparison dedup) | `8e73682` | `test_ws_gap_aggregate_fill_inserted_when_per_trade_undercovers` |
| P2 round 9 | `r3213223267` (UPDATE→filled) | `8a6413b` | `test_order_update_fully_matched_routes_to_filled` |
| P1 round 10 | `r3213231396` (open UPDATE persist) | `0ddb284` + `b52d0fc` | `test_open_update_with_size_matched_persists_aggregate` + 4 GATE-mandated regressions |
| P1 round 11 | `r3213247691` (larger-of hydration) | `1f77598` + `8197373` | `test_cancel_uses_larger_agg_when_per_trade_undercovers` |

Skipped (CMD-ratified): `r3213074598` (markets:[] subscribe). Per
WARP🔹CMD's earlier ratification, the empty `markets` array streams
every event for the apiKey — matches open-source Polymarket WS
clients. Documented as out-of-scope.

---

## NEXT GATE

Return to WARP🔹CMD for final merge decision.
