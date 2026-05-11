# WARP•SENTINEL Validation — crusaderbot-fast-copy-execution

**Branch:** WARP/sentinel-crusaderbot-fast-copy-execution
**Source PR:** #948 — WARP/crusaderbot-fast-copy-execution
**Source Issue:** #949
**Source Forge Report:** projects/polymarket/crusaderbot/reports/forge/crusaderbot-fast-copy-execution.md
**Validation Tier:** MAJOR
**Claim Level:** FULL RUNTIME INTEGRATION
**Verdict:** APPROVED
**Score:** 97/100
**Critical Issues:** 0
**Date:** 2026-05-11 15:25 Asia/Jakarta

---

## 1. Environment

- Environment: dev (paper posture)
- Infra: warn-only
- Risk: ENFORCED
- Telegram: warn-only
- Active project: projects/polymarket/crusaderbot
- Activation guards (read from projects/polymarket/crusaderbot/config.py):
  - USE_REAL_CLOB: False (default)
  - EXECUTION_PATH_VALIDATED: False
  - CAPITAL_MODE_CONFIRMED: False
  - ENABLE_LIVE_TRADING: True (legacy default — fly.toml [env] overrides to False; documented in PROJECT_STATE [KNOWN ISSUES])

---

## 2. Validation Context

PR #948 introduces the active copy-trade execution service `CopyTradeMonitor` (`services/copy_trade/monitor.py`). The service polls leader wallets every `COPY_TRADE_MONITOR_INTERVAL` (default 60s), routes each unprocessed leader trade through `TradeEngine.execute()` (which gates on the existing 13-step risk gate before paper fill), and records spend + idempotency rows in two new tables.

Validation target (from issue #949):
- Normal copy-trade path routes through TradeEngine.execute() and cannot bypass risk gate.
- Idempotency safe under concurrent scheduler ticks.
- Daily spend cap + min trade size + reverse_copy logic correct.
- APScheduler registration safe (max_instances=1, coalesce, no duplicate execution).
- Kill switch honored before task execution.
- PAPER ONLY posture preserved (no activation guard flips).
- Tests cover runtime path and failure cases.
- State files + forge report match code truth.

Out-of-scope (explicitly excluded by forge): live trading activation, real CLOB, notifications UI, referral/fee, copy-trade exit tracking, leader bankroll auto-discovery.

---

## 3. Phase 0 Checks

| Check | Result | Evidence |
| --- | --- | --- |
| PR #948 exists and open | PASS | mergeable_state="unstable", state="open" |
| Branch matches WARP/{feature} exactly | PASS | head.ref="WARP/crusaderbot-fast-copy-execution" |
| Forge report at correct path + 6 sections | PASS | projects/polymarket/crusaderbot/reports/forge/crusaderbot-fast-copy-execution.md (sections 1–6 present plus metadata) |
| PROJECT_STATE.md updated, full timestamp | PASS | "Last Updated : 2026-05-11 14:30" (Asia/Jakarta), 7 sections preserved |
| No `phase*/` folders | PASS | `find . -type d -name "phase*"` returned empty |
| No phase imports in changed files | PASS | grep -rn "from .*phase[0-9]" against changed files returned empty |
| Hard delete policy followed | PASS | All new files in domain-correct paths; no shims |
| No hardcoded secrets in changed files | PASS | monitor.py / scheduler.py / engine.py contain no API keys, tokens, .env values |
| No full Kelly (a=1.0) | PASS | risk gate uses K.KELLY_FRACTION; copy monitor passes max_position_pct=0.10 only |
| No `except: pass` in runtime paths | PASS | grep returned no matches in changed files |
| No `threading` module usage | PASS | grep returned only docstring references in changed files |
| `python -m py_compile` on changed files | PASS | All 5 changed Python files compile clean |
| `pytest tests/test_fast_track_b.py -q` | PASS | 23 passed in 0.52s |

---

## 4. Findings

### 4.1 Runtime path through TradeEngine (Phase 1 — Functional, Phase 2 — Pipeline)

- monitor.py:262–263 — `result = await _engine.execute(signal)` is the ONLY execution call site in the monitor. There is no direct `paper.execute` / `router.execute` import or call.
- monitor.py:48 — imports only `from ..trade_engine import TradeEngine, TradeSignal`. No execution-path imports bypass the engine.
- monitor.py:58 — `_engine: TradeEngine = TradeEngine()` is a module-level stateless singleton; safe per `engine.py:104` "One instance is safe to share across the full process lifetime".
- engine.py:120–123 — `TradeEngine.execute` calls `_risk_evaluate(gate_ctx)` BEFORE `_router_execute`. Confirmed: `if not gate_result.approved: return TradeResult(approved=False, ...)`.
- engine.py:140–160 — `_router_execute` is only reached when `gate_result.approved=True`; `chosen_mode=gate_result.chosen_mode`. Risk gate cannot be bypassed.
- gate.py:279 — `chosen_mode = "live" if _passes_live_guards(ctx, settings) else "paper"`. Since `EXECUTION_PATH_VALIDATED=False` and `CAPITAL_MODE_CONFIRMED=False`, `_passes_live_guards` returns False → `chosen_mode="paper"` always in current posture.
- TC01 (test_fast_track_b.py:147–167) verifies engine.execute is awaited with full TradeSignal; TC05 verifies rejection path is honored.

Verdict: PASS — copy-trade signals cannot bypass the risk gate or reach a live path.

### 4.2 Idempotency safety under concurrent scheduler ticks (Phase 4 — Async Safety)

- migrations/020_copy_trade_execution.sql:14–15 — `UNIQUE (user_id, task_id, leader_trade_id)` constraint enforced at the DB.
- monitor.py:330–337 — `_mark_processed` uses `INSERT … ON CONFLICT DO NOTHING`. Safe to retry; concurrent ticks cannot double-insert.
- monitor.py:308–321 — `_is_already_processed` reads via SELECT (cheap path); even if two ticks race past this check, the unique constraint + ON CONFLICT DO NOTHING in `_mark_processed` prevents duplicate state.
- Defense-in-depth: monitor.py:235 builds `idempotency_key = f"copy_{task_id}_{leader_trade_id}"`; TradeEngine forwards this to the paper engine, which has its own idempotency dedup (TradeEngine returns `mode="duplicate"` per engine.py:163–168). So even if monitor races itself OR the DB row is missed, paper engine acts as a second idempotency anchor.
- Scheduler registration (scheduler.py:543–545) declares `max_instances=1, coalesce=True` — APScheduler will not overlap monitor ticks within a single process.
- TC04 (test_fast_track_b.py:225–243) verifies duplicate rejection path; TC06 verifies leader_trade_id passed to mark_processed correctly.

Verdict: PASS — three independent layers (APScheduler max_instances=1, DB UNIQUE constraint, paper engine idempotency).

### 4.3 Daily spend cap, min trade size, reverse_copy (Phase 5 — Risk Rules)

- monitor.py:158–165 — `min_trade_size` filter: rejects if `leader_size < float(task.min_trade_size)`. TC02 verifies.
- monitor.py:168–177 — `_get_daily_spend` reads from `copy_trade_daily_spend`; rejects when `remaining_spend <= 0`. TC03 verifies (returns 0 spend earlier from gate cap).
- monitor.py:189–197 — Cap-after-compute: `copy_size = min(copy_size, remaining_spend)`; second floor check rejects if below `MIN_TRADE_SIZE_USDC`. TC10 verifies.
- monitor.py:356–369 — `_record_spend` uses `INSERT … ON CONFLICT … DO UPDATE SET spend_usdc = copy_trade_daily_spend.spend_usdc + EXCLUDED.spend_usdc` — additive upsert is atomic under PostgreSQL.
- monitor.py:461–469 — `_resolve_side` normalises BUY/SELL → yes/no; if `reverse_copy=True`, flips yes↔no. TC09 confirms `buy + reverse_copy=True` → `signal.side == "no"`.
- monitor.py:198–207 — Unknown sides ("HOLD", garbled) rejected before TradeEngine call. TC08 verifies.

Verdict: PASS — all four constraints exercised in tests with positive and negative cases.

### 4.4 APScheduler registration (Phase 4 — Async Safety, Phase 7 — Infra)

- scheduler.py:27 — `from .services.copy_trade import monitor as copy_trade_monitor`
- scheduler.py:543–545:
```
sched.add_job(copy_trade_monitor.run_once, "interval",
              seconds=s.COPY_TRADE_MONITOR_INTERVAL,
              id="copy_trade_monitor", max_instances=1, coalesce=True)
```
- config.py:148 — `COPY_TRADE_MONITOR_INTERVAL: int = 60` (overridable via env).
- Job ID is unique (`copy_trade_monitor`) — no collision with existing jobs (signal_scan, signal_following_scan, exit_watch, order_lifecycle, redeem, resolution, sweep, daily_pnl_summary).
- `coalesce=True` collapses missed ticks; `max_instances=1` prevents overlap.

Verdict: PASS.

### 4.5 Kill switch honored (Phase 5 — Risk Rules)

- monitor.py:73–75 — `if await kill_switch_is_active(): logger.warning(...); return` — first statement of `run_once()` before any DB read or API call.
- TC11 (test_fast_track_b.py:407–418) — when kill switch returns True, `list_active_tasks` is NOT awaited and `_engine.execute` is NOT awaited.

Verdict: PASS — kill switch exits at tick entry without touching any execution-path call.

### 4.6 PAPER ONLY posture (Phase 5 — Risk Rules)

- Diff against config.py: only adds `COPY_TRADE_MONITOR_INTERVAL: int = 60`. ENABLE_LIVE_TRADING / EXECUTION_PATH_VALIDATED / CAPITAL_MODE_CONFIRMED / USE_REAL_CLOB are NOT touched.
- monitor.py contains zero references to ENABLE_LIVE_TRADING, EXECUTION_PATH_VALIDATED, CAPITAL_MODE_CONFIRMED, USE_REAL_CLOB.
- TradeSignal.trading_mode is read from `user_settings.trading_mode` (default 'paper' per `_load_user_context` COALESCE in monitor.py:382). Risk gate forces chosen_mode=paper unless guards flip.

Verdict: PASS — no live activation surface added.

### 4.7 Test coverage (Phase 1 — Functional)

- 23/23 tests pass in 0.52s (locally re-run on sentinel branch; matches forge report).
- 13 async integration tests cover happy path + 8 distinct rejection reasons + idempotency + kill switch + wallet API failure isolation.
- 10 pure-helper tests cover `_extract_trade_id`, `_resolve_side`, `_make_idempotency_key`, `_compute_copy_size`.

Coverage adequacy: hermetic with mocks at the DB and TradeEngine boundary. No real DB integration test, but the migration is straightforward and the DB calls are SELECT/INSERT with explicit ON CONFLICT semantics — boundary contract is well-defined.

Verdict: PASS — adequate for FULL RUNTIME INTEGRATION at paper tier.

### 4.8 State + report sync (handoff prerequisite)

- PROJECT_STATE.md (line 16) "Fast Track Track B -- Copy Trade execution FORGE complete; PR open; WARP•SENTINEL validation required before merge." — matches forge.
- PROJECT_STATE.md (line 30) NEXT PRIORITY references the correct forge report path. Sentinel handoff intact.
- WORKTODO.md and ROADMAP.md updated alongside (not re-read for content; presence verified by git diff).
- CHANGELOG.md updated.

Verdict: PASS.

---

## 5. Score Breakdown

| Category | Weight | Score | Reasoning |
| --- | --- | --- | --- |
| Architecture | 20 | 20 | Single execution path through TradeEngine; no live surface; clean module boundaries; stateless singleton |
| Functional | 20 | 20 | 23/23 tests pass; covers happy path + every rejection mode + kill switch + wallet API failure |
| Failure Modes | 20 | 18 | Wallet API exception isolated (TC13); risk gate rejection persisted to idempotency (TC05); kill switch (TC11); no explicit DB-failure injection test (−2) |
| Risk | 20 | 20 | Kelly enforced via existing risk gate; idempotency UNIQUE constraint; daily spend cap atomic upsert; min_trade_size; max_position 10% via scaler; reverse_copy correct |
| Infra + Telegram | 10 | 9 | Migration clean (UNIQUE + indexes + ON DELETE CASCADE); scheduler registered correctly; Telegram alert wiring out-of-scope (Track C) (−1) |
| Latency | 10 | 10 | 60s tick cadence appropriate; per-wallet grouping minimises API calls; wallet_watcher already enforces 1 req/s rate limit + 5s timeout |
| **Total** | **100** | **97** | |

---

## 6. Critical Issues

None found.

---

## 7. Status

**APPROVED**

Score 97/100, zero critical issues, Phase 0 fully passed, all eight validation targets from issue #949 satisfied.

---

## 8. PR Gate Result

| Item | Result |
| --- | --- |
| Source PR #948 status | Open, mergeable_state="unstable" (CI/checks may be pending — independent of validation) |
| SENTINEL PR target | Source branch `WARP/crusaderbot-fast-copy-execution` (FORGE PR #948 still open per branch/PR rules) |
| Sentinel verdict for merge gate | APPROVED — WARP🔹CMD may merge after final review |
| Activation guard flip required | NO — paper posture preserved |

---

## 9. Broader Audit Finding

Broader audit was not requested. This validation is bounded to the audit scope declared in issue #949 — copy-trade execution lane. No expansion taken.

Pre-existing repo-wide observations (not blockers, do not affect this verdict):
- ENABLE_LIVE_TRADING code default `True` in config.py:134. Production posture remains correct because fly.toml [env] overrides to False — already documented in PROJECT_STATE [KNOWN ISSUES] and tracked under WARP/config-guard-default-alignment. No new exposure introduced by this PR.

---

## 10. Reasoning

The change is tightly scoped: one new service module, one migration, one test file, plus three small modifications (scheduler wire-up, repository helper, services init re-export, config interval). The execution path is a single arrow — `run_once → TradeEngine.execute → risk gate → router (paper)` — with no escape hatches. Three independent idempotency layers (APScheduler max_instances=1, DB UNIQUE constraint with ON CONFLICT DO NOTHING, paper engine idempotency dedup) prevent double fills under any plausible race. The kill switch is the very first statement in `run_once`, before any DB or API call. PAPER ONLY posture is preserved by construction — the monitor never touches activation guards, never imports the live execution router, and routes all signals through the same gate that enforces `chosen_mode=paper` unless every guard flips. Test coverage is hermetic but exercises every claimed code path including the failure modes that matter most: wallet API down, risk gate rejection, kill switch active, idempotency duplicate, all three spend-cap floors, and the reverse_copy flip. The forge report matches code truth exactly.

---

## 11. Fix Recommendations

None required for merge. Defer-only suggestions captured in section 13.

---

## 12. Out-of-scope Advisory

Out-of-scope items (per issue #949 and forge report):
- Live trading activation surface — explicitly NOT in scope.
- Real CLOB integration for copy trades — explicitly NOT in scope.
- Telegram notifications for copy-trade entry/exit — Track C.
- Copy-trade exit tracking (leader-exit detection) — deferred per forge.
- Leader bankroll auto-discovery via Gamma API — deferred per forge.

These were correctly excluded and are not part of this verdict.

---

## 13. Deferred Minor Backlog

- [DEFERRED-P3] `monitor._extract_price` falls back to 0.5 when leader trade has no price field — defensive only, no real Polymarket activity record lacks `price`. Real-mode hardening should pull from `markets` table.
- [DEFERRED-P3] `monitor._extract_liquidity` falls back to 50_000.0 USDC when absent — generous to avoid spurious risk-gate rejection in paper mode; live activation must replace with real liquidity lookup.
- [DEFERRED-P3] `monitor._get_daily_spend` uses UTC date; user-subjective day (Asia/Jakarta UTC+7) wraps ~7h earlier than UTC midnight. Cosmetic, no safety implication.
- [DEFERRED-P3] `actual_size = float(result.final_size_usdc) if result.final_size_usdc else copy_size` (monitor.py:290) — fallback to `copy_size` is unreachable when `result.approved=True` (TradeEngine guarantees `final_size_usdc`); defensive but slightly misleading. Minor cleanup.
- [DEFERRED-P2] No DB-failure injection test (e.g., asyncpg pool acquire raises). Wallet API failure is covered (TC13). Add a DB-failure test in a follow-up to harden Phase 3 (failure modes) coverage.

---

## 14. Telegram Visual Preview

Out of scope for this validation lane (Telegram notifications are Track C).

```
[Telegram preview deferred — Track C will add copy-trade entry/exit/duplicate alert templates]
```

---

End of WARP•SENTINEL report.
