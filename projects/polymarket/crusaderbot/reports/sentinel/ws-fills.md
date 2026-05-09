# WARP•SENTINEL REPORT — ws-fills

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Verdict: APPROVED
Stability Score: 98 / 100
Critical Issues: 0
PR: #915 — WARP/CRUSADERBOT-PHASE4D-WEBSOCKET-FILLS
Head SHA: 661582dae6632353421168ce1f21154f46d4abc5
Forge Source: projects/polymarket/crusaderbot/reports/forge/ws-fills.md

---

## TEST PLAN

Environment: `dev` (paper) — runtime broker connection NOT exercised; SENTINEL audit reads code + hermetic test evidence + CI gate posture. `USE_REAL_CLOB` default `False`; no real socket opens.

Phases executed:

- Phase 0 — Pre-test gate (forge report path/sections, branch alignment, structure rules).
- Phase 1 — Paper-mode safety: `ClobWebSocketClient.start()` no-op + `ws_connect` / `ws_watchdog` short-circuit + connect-factory never invoked.
- Phase 2 — Protocol contract: `/ws/user` URL, `{auth:{apiKey,secret,passphrase},type:user,markets:[]}` subscribe, literal `PING` cadence at 10s.
- Phase 3 — Reconnect math: exponential backoff `base * 2^(n-1)` + ±25% jitter, cap at `WS_RECONNECT_MAX_DELAY_SECONDS`, attempt counter resets on successful open, stop-event exits backoff cleanly.
- Phase 4 — Heartbeat: missed-pong within `interval + timeout` recycles socket; pong stamp keeps it alive.
- Phase 5 — Loop containment: malformed JSON / non-dict / unknown `event_type` / raising dispatcher do NOT crash the read loop.
- Phase 6 — Trade status gate: CONFIRMED allow-list only; MATCHED / MINED / RETRYING / FAILED / rejected never emit `EVENT_FILL`.
- Phase 7 — `handle_ws_fill` records-only: per-trade fill insert + `positions.current_price` UPDATE; no terminal mark, no Telegram on partial.
- Phase 8 — Agg-fill dedup: when per-trade WS fills are present, follow-on `agg-{broker}` rows are skipped.
- Phase 9 — Polling fallback: still registered; per-row dedup via `fills.fill_id` unique constraint + `ON CONFLICT DO NOTHING`.
- Phase 10 — Activation guards: `USE_REAL_CLOB=False` default + not flipped by CI; `ENABLE_LIVE_TRADING` not read or mutated by the WS path.

---

## FINDINGS

### Phase 0 — Pre-test gate — PASS

- Forge report exists at `projects/polymarket/crusaderbot/reports/forge/ws-fills.md` with all six mandatory sections and full Tier / Claim / Validation Target / Not in Scope / Suggested Next Step metadata (forge §preamble, §1–§6).
- Branch under audit: `WARP/CRUSADERBOT-PHASE4D-WEBSOCKET-FILLS` matches the WARP🔹CMD declaration (case-sensitive) — confirmed via `git rev-parse` after `git checkout` (Claude Code initially auto-named a `claude/…` branch which is not in scope for SENTINEL output per CLAUDE.md branch verification rule; SENTINEL operates on the proper WARP branch).
- No `phase*/` folders in the changeset.
- Implementation evidence present in source + tests.

### Phase 1 — Paper-mode safety — PASS

- `integrations/clob/ws.py:135` — `start()` short-circuits `if not s.USE_REAL_CLOB: return` BEFORE spawning `_run_loop`; the run task is never created and `_open_connection` (and therefore `connect_factory`) is unreachable.
- `scheduler.py:401` — `ws_connect()` returns immediately when `USE_REAL_CLOB=False`, BEFORE constructing the singleton, so the factory is not even reachable from the scheduler entry point.
- `scheduler.py:421` — `ws_watchdog()` mirrors the same guard.
- Test `tests/test_clob_ws.py:97 test_paper_mode_start_is_noop_and_factory_never_called` injects an asserting connect factory and verifies it is never awaited.
- Test `tests/test_lifecycle_ws.py:380 test_ws_connect_noop_in_paper_mode` confirms scheduler-level no-op.

### Phase 2 — Protocol — PASS

- `config.py:174` — `CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/user"` matches the validation scope `/ws/user`.
- `integrations/clob/ws.py:269-277` — subscribe frame is `{"auth":{"apiKey":…,"secret":…,"passphrase":…},"type":"user","markets":[]}`. All three credential fields present.
- `config.py:183` — `WS_HEARTBEAT_INTERVAL_SECONDS = 10` (default) matches the "literal PING 10s cadence" requirement.
- `integrations/clob/ws.py:379` — `await ws.send("PING")` (literal text). PONG reply is detected before JSON parse at `ws.py:299-303`.
- Test `tests/test_clob_ws.py:146 test_start_opens_socket_and_sends_subscribe_with_auth` asserts the exact subscribe payload shape.

### Phase 3 — Reconnect backoff + jitter + cap — PASS

- `integrations/clob/ws.py:59-72` `_backoff_delay(attempt, max_delay, base=1.0)`: `raw = base * 2^(attempt-1)`; `capped = min(raw, max_delay)`; jitter band ±25% via `random.uniform(-jitter, +jitter)`; clamped at `0.0` floor.
- Cap is `WS_RECONNECT_MAX_DELAY_SECONDS = 60` (`config.py:178`).
- `ws.py:213` — `self._connect_attempts = 1` resets on successful open inside `_connect_and_read`; the next disconnect starts the ramp from zero rather than continuing the prior outage's backoff.
- `ws.py:188-194` — backoff sleeps via `asyncio.wait_for(self._stop_event.wait(), timeout=delay)`; `stop()` setting the event causes the wait to return → `_run_loop` returns cleanly without retry.
- Tests: `test_clob_ws.py:123 test_backoff_delay_caps_at_max_delay`, `test_clob_ws.py:130 test_backoff_delay_scales_exponentially_under_cap`, `test_clob_ws.py:365 test_socket_end_triggers_reconnect_attempt`.

### Phase 4 — Heartbeat timeout → socket recycle — PASS

- `integrations/clob/ws.py:339-386` `_heartbeat_loop`: deadline is `interval + timeout` (default 10 + 10 = 20s). On every interval boundary the loop checks `_clock() - _last_pong_at > deadline` BEFORE the next PING goes out (Codex P1 fix on PR #915 — comment at ws.py:347-353), so a silent socket is detected within one interval window and the broker's silence-disconnect heuristic does not race the next doomed PING.
- On miss: `await ws.close()` (`ws.py:372`); `_run_loop` then enters backoff and reconnects.
- `_dispatch_raw` stamps `_last_pong_at` on either a literal `PONG` text frame (`ws.py:299-303`) or a JSON `{type:pong}` / `{event_type:pong}` envelope (`ws.py:311-316`).
- Tests: `test_clob_ws.py:294 test_heartbeat_pong_keeps_socket_alive` (3 ping cycles), `test_clob_ws.py:330 test_heartbeat_timeout_recycles_socket`.

### Phase 5 — Loop containment — PASS

- JSON parse failure: `integrations/clob/ws.py:305-309` `try / except (TypeError, ValueError)` → log + return; the read loop never sees the exception.
- Dispatcher exception: `ws.py:319-326` `try / except Exception` around `_fanout`; logs at ERROR with `exc_info` and continues the per-event for-loop.
- Unknown event_type: `integrations/clob/ws_handler.py:337-338` returns `[]` after a DEBUG log (no warning, no raise). Recognised channel chatter (`last_trade_price`, `book`, `price_change`, `tick_size_change`, `pong`, `subscribed`) is silently dropped at `ws_handler.py:331-335`.
- Non-dict / non-list payload: `ws_handler.py:296-298` drops with DEBUG log.
- Tests: `test_clob_ws.py:219 test_unknown_frame_does_not_crash_loop`, `test_clob_ws.py:251 test_dispatcher_exception_is_contained`, `test_clob_ws_handler.py:297 test_unknown_event_type_emits_nothing_and_does_not_raise`, `test_clob_ws_handler.py:303 test_non_dict_message_drops_silently`.

### Phase 6 — Trade status gate (CONFIRMED allow-list) — PASS

- `integrations/clob/ws_handler.py:98-103` allow-list `_TRADE_STATUS_SETTLED = {"confirmed","completed","complete","settled"}`.
- `ws_handler.py:106-126` `_is_settled_trade_status` strips `trade_status_` prefix, lowercases, and checks against the allow-list. MATCHED / MINED / RETRYING / FAILED / rejected / cancelled all return `False` → `parse_message` returns `[]` at `ws_handler.py:307-315` BEFORE `_normalise_fill` runs, so no `EVENT_FILL` is emitted.
- Frames with no `status` field default to `True` (allow); intentional per `ws_handler.py:113-118` to keep older user-channel emissions and integration tests working. Validation scope explicitly lists "MATCHED/MINED/FAILED never emit" — all three are blocked.
- Test `test_clob_ws_handler.py:185 test_trade_frame_with_non_settled_status_emits_no_fill` parametrises the full reject set: `RETRYING`, `FAILED`, `TRADE_STATUS_FAILED`, `rejected`, `Cancelled`, `TRADE_STATUS_RETRYING`, `MATCHED`, `MINED`, `TRADE_STATUS_MATCHED`, `TRADE_STATUS_MINED`. All assert `parse_message(frame) == []`.
- Test `test_clob_ws_handler.py:203 test_trade_frame_with_settled_status_emits_fill` covers the accept set: `CONFIRMED`, `TRADE_STATUS_CONFIRMED`, `completed`, `SETTLED`.

### Phase 7 — handle_ws_fill records-only — PASS

- `domain/execution/lifecycle.py:615-700` — handler inserts a `fills` row via `_record_fills_in_conn` and `UPDATE positions SET current_price` on the open position only. There is no `UPDATE orders SET status='filled'` and no call into `_on_fill` / `_on_cancel` / `_terminal_close`. Telegram notification is intentionally deferred to the terminal path (`lifecycle.py:637-639` doc).
- Already-terminal short-circuit at `lifecycle.py:656-661` (status not in `STATUS_OPEN` → drop).
- Unknown broker id at `lifecycle.py:649-655` → drop with INFO log.
- Test `test_lifecycle_ws.py:177 test_ws_fill_records_partial_only_no_terminal_update` asserts `terminal_updates == []` AND `notify_user.assert_not_awaited()` AND `len(fills_inserted) == 1`.
- Test `test_lifecycle_ws.py:217 test_ws_partial_fills_accumulate_without_terminating` exercises 3 sequential WS fills, all recorded, zero terminal updates.

### Phase 8 — Agg-fill dedup — PASS

- `domain/execution/lifecycle.py:533-570` — `_record_fills_in_conn` detects an all-`agg-` payload, queries `SELECT 1 FROM fills WHERE order_id=$1 AND fill_id NOT LIKE 'agg-%' LIMIT 1`, and skips the insert when any per-trade row already exists. Per-trade rows from WS keep their canonical fill_ids (`{trade_id}-m-{idx}` / `{trade_id}-t`), so the `agg-{broker}` rollup synthesised by `_broker_fills` for terminal closure does not double-count shares.
- Test `test_lifecycle_ws.py:304 test_ws_fill_then_order_update_filled_skips_aggregate_row` walks WS fill → order_update(filled) and asserts no `agg-` row is inserted on top of the per-trade row.

### Phase 9 — Polling fallback — PASS

- `domain/execution/lifecycle.py:590-599` — `INSERT INTO fills … ON CONFLICT (fill_id) DO NOTHING`; the `fills.fill_id` unique constraint (Phase 4C migration 015, already audited) guarantees the second writer's per-fill row is silently dropped.
- Phase 4C `poll_once()` is unchanged by this PR; `scheduler.py:541-548` still registers `order_lifecycle.poll_once` on the existing `ORDER_POLL_INTERVAL_SECONDS=30` interval. Polling remains the fallback when the WS path is silent or paper-mode-disabled.
- Test `test_lifecycle_ws.py:237 test_ws_then_poll_dedup_via_fill_id_unique_constraint` asserts the WS path issues no terminal write, leaving polling free to race-win cleanly.
- Test `test_lifecycle_ws.py:334 test_polling_only_aggregate_fill_still_inserted_when_no_per_trade` confirms the agg-dedup guard does NOT block the synthetic row when per-trade WS rows are absent (polling-only flow).

### Phase 10 — Activation guards (CI posture) — PASS

- `config.py:120` — `USE_REAL_CLOB: bool = False` (default OFF).
- No occurrence of `USE_REAL_CLOB` in `.github/workflows/` (verified via repo-wide grep). CI never overrides the default to True; the connect factory is therefore unreachable from any CI test path.
- `ENABLE_LIVE_TRADING` is NOT read or mutated by `integrations/clob/ws.py`, `integrations/clob/ws_handler.py`, `domain/execution/lifecycle.py` (`handle_ws_*`), or the new scheduler hooks (verified via grep). The forge report claim "ENABLE_LIVE_TRADING is not required by the WS path" is accurate.
- Pre-existing PROJECT_STATE known-issue (config.py:134 `ENABLE_LIVE_TRADING: bool = True` legacy code default; fly.toml `[env]` overrides to `"false"`) is OUT OF SCOPE for this PR — not introduced or modified here.
- Scheduler wiring: `scheduler.py:550-554` registers `ws_connect` (`date` trigger, fires once) and `ws_watchdog` (`interval` 60s, `max_instances=1`, `coalesce=True`) inside `setup_scheduler`. `main.py:196-197` calls `await ws_shutdown()` from the FastAPI lifespan teardown after `scheduler.shutdown()`.
- Test `test_lifecycle_ws.py:430 test_setup_scheduler_registers_ws_jobs` asserts both job ids are registered.

### Test Posture (informational)

- 12 + 23 + 16 = 51 hermetic tests across `test_clob_ws.py` / `test_clob_ws_handler.py` / `test_lifecycle_ws.py` (forge report quotes 47; the delta is parametrise expansion on the trade-status set). All 51 are constructed with injected fakes — no real socket, no real DB, no real Telegram.

---

## CRITICAL ISSUES

None.

---

## STABILITY SCORE

| Dimension | Weight | Score | Notes |
|---|---|---|---|
| Architecture | 20 | 19 | Clean transport/parser/lifecycle split; triple paper-mode guard (start + ws_connect + ws_watchdog); no shims; soft `websockets` import keeps unit tests hermetic. -1 for forge-report drift on heartbeat default. |
| Functional | 20 | 20 | Every validation-scope item has direct code + test evidence. |
| Failure modes | 20 | 20 | Malformed JSON, non-dict, unknown event_type, raising dispatcher, socket end, missed pong, missing ids — all caught and exercised. |
| Risk rules | 20 | 20 | Kelly / position cap / loss limit / drawdown / kill switch / dedup unchanged. WS path enforces capital safety via `USE_REAL_CLOB=False` triple guard. |
| Infra + Telegram | 10 | 9 | Telegram on partial fill correctly suppressed to avoid misleading "Order filled" message; terminal path owns user-facing notification. -1 for forge prose drift on subscribe shape. |
| Latency | 10 | 10 | Push-based fills supersede 30s polling cadence; 10s heartbeat matches Polymarket disconnect-on-silence; reconnect cap 60s acceptable. |
| **Total** | **100** | **98** |  |

---

## GO-LIVE STATUS

**APPROVED** — score 98 / 100, zero critical issues, every validation-scope item has direct code + hermetic test evidence.

Reasoning:

- Capital-safety boundary holds at three independent layers (`ClobWebSocketClient.start`, `ws_connect`, `ws_watchdog`); the connect factory is unreachable from any code path while `USE_REAL_CLOB=False`.
- Trade-status gate is a strict allow-list; the documented MATCHED → MINED → CONFIRMED progression cannot credit positions on non-final states.
- Records-only `handle_ws_fill` plus agg-fill dedup eliminates the double-count failure mode raised in Codex P2 review.
- Polling fallback is preserved; the dual-source model is naturally idempotent at `fills.fill_id` unique constraint and `UPDATE … RETURNING id` race-loss.
- Loop containment verified across malformed JSON, unknown event types, non-dict frames, and raising dispatchers — no path can crash the read loop.

Conditions for WARP🔹CMD merge:

1. Wait for CI checks on head SHA `661582da` to return green. At audit time `pull_request_read get_status` reports `state=pending, total_count=0` — checks have not yet completed (or have not yet been registered against this SHA).
2. Confirm the operator-facing posture: `USE_REAL_CLOB` stays `False` in prod until the live-readiness gate is explicitly flipped (PROJECT_STATE [NEXT PRIORITY] line tracks this).

---

## FIX RECOMMENDATIONS

Priority order — none of these block APPROVED.

1. **LOW (doc drift, post-merge fix-forward):** forge report `ws-fills.md:27` and `:100` state `WS_HEARTBEAT_INTERVAL_SECONDS = 30`; actual `config.py:183 = 10`. Update the forge prose to match the post-Codex-P1 cadence (10s) so a future reader is not misled by the 30s figure.
2. **LOW (doc drift, post-merge fix-forward):** forge architecture diagram `ws-fills.md:130` lists `{"type":"subscribe","channel":"user","auth":{...}}` subscribe shape; actual `integrations/clob/ws.py:269-277` emits `{"auth":{apiKey,secret,passphrase},"type":"user","markets":[]}`. Code matches Polymarket docs and validation scope; only the forge prose drifted.
3. **INFO (operator posture):** `ENABLE_LIVE_TRADING` legacy code default of `True` (`config.py:134`) remains a pre-existing PROJECT_STATE [KNOWN ISSUES] item. Not introduced here; flagged again because it widens the "easy to flip" surface for any future code path that reads it. Continue to track via the deferred `WARP/config-guard-default-alignment` lane.
4. **INFO (heartbeat boundary edge):** as the forge §5 already notes, the `_clock() - _last_pong_at > deadline` check has an off-by-one at the exact deadline boundary. Acceptable given heartbeat tolerances are O(seconds). No fix required.

---

## TELEGRAM PREVIEW

The WS path adds NO new alert events — by design. Per `lifecycle.py:637-639` the records-only handler defers user-facing notifications to the terminal close path so a partial fill cannot produce a misleading "Order filled" message. Existing alerts continue to fire from the Phase 4C terminal handlers:

- `_on_fill` (terminal, via `handle_ws_order_update(status=filled)` OR polling): `✅ *Order filled*` with market / side / size / price.
- `_on_cancel`: `❌ *Order cancelled*` with refund accounting on partial fill.
- `_on_expiry`: `⌛️ *Order expired*` with refund accounting on partial fill.
- `_mark_stale` (operator-only): `⚠️ *STALE ORDER*` with poll attempts + reason.

Operator dashboard (`/ops_dashboard`) and `/health` are untouched by this PR.

Commands referenced:

- `/health` — unchanged; future enhancement (out of scope) could surface `get_ws_client().is_alive()` for WS liveness in the demo-readiness payload.
- `/kill` / `/resume` — unchanged kill switch path remains the operator's emergency stop.

