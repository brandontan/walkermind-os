# WARP•R00T — rpc-watcher-hardening

Full-surface adversarial audit (owner directive 2026-06-11: bring all four
surfaces to verified live+paper readiness) + hardening fixes for the two live
production failure modes. Branch: `WARP/root-rpc-watcher-hardening`.

- Validation Tier   : MAJOR
- Claim Level       : NARROW INTEGRATION
- Validation Target : Polygon RPC call boundary (timeout/retry/adaptive scan),
  deposit-watcher tick failure surface, relayer call deadline, cset market
  loader resilience. Audit verdicts for all other surfaces are evidence
  statements, not code changes.
- Not in Scope      : risk constants / Kelly a=0.25 / ENABLE_LIVE_TRADING + 5
  guards / kill_switch / strategy entry-exit logic / order submit paths /
  migrations / per-user execution lane / frontend code.
- Suggested Next    : WARP•R00T merge on CI green (owner full-bypass);
  owner ops sequence below; FOLLOW-UP lanes per prioritized roadmap (§5).

---

## 1. What was built

Five production fixes + one state-hygiene repair, all verified by new tests:

1. **Polygon RPC hard deadline** (`integrations/polygon.py`). The
   `AsyncHTTPProvider` had NO request timeout — aiohttp defaults to
   total=300s, and a peer that accepts TCP but never answers wedges the call
   (the 2026-06-11 06:12 UTC scheduler stall: one hung no-timeout call froze
   an APScheduler `max_instances=1` slot permanently). Now: explicit
   `ClientTimeout(total=POLYGON_RPC_TIMEOUT_SECONDS)` (default 20s) on the
   provider AND `asyncio.timeout()` around every RPC await
   (`latest_block` / `get_usdc_balance` / `get_native_balance` /
   `gas_price_gwei` / `scan_usdc_transfers`) as a belt to the suspender.
2. **Retry predicate gap closed** (`integrations/polygon.py:_retry`). web3
   surfaces non-2xx HTTP (Alchemy 429 throttle, 5xx) as aiohttp
   `ClientResponseError` — NOT `Web3RPCError`/`ConnectionError` — so the old
   predicate reraised on the FIRST throttled response with zero retries.
   `ClientError` added; `TimeoutError` now also covers the new asyncio
   deadlines (3.11+: `asyncio.TimeoutError is TimeoutError`).
3. **Adaptive eth_getLogs range** (`integrations/polygon.py:scan_from_cursor`).
   Providers cap getLogs by block range / response size per plan; a fixed
   1000-block span turns such a cap into a deterministic EVERY-TICK failure —
   exactly the observed gate-4 outage shape (chain_cursor pinned at block 0,
   prod-verified again this session via read-only Supabase: both cursors
   still at migration-seed state, deposits table empty). On `Web3RPCError`
   the span now halves down to a 31-block floor; a smaller successful scan
   still advances the cursor, so the watcher self-heals instead of wedging.
   Transport errors (timeout/throttle/drop) are deliberately NOT halved.
4. **Watcher tick failure surface completed** (`scheduler.py`). The
   `_read_cursor` stage was unguarded — an exception there escaped
   `watch_deposits` entirely, bypassing the failure-streak escalation and the
   `watch_deposits DOWN` Sentry alarm (it surfaced only as an anonymous
   APScheduler "job raised an exception"). Now staged as `cursor read`.
   Every failure line additionally carries `cursor/head/watched/lookback` +
   `repr(exc)` so ONE log read pins the exact failing request — the block-0
   outage hid for five weeks behind a context-free WARNING.
5. **Relayer SDK calls bounded** (`wallet/custody.py:_execute_usdc_transfer`).
   `client.execute` + `response.wait` (blocking SDK, run via
   `asyncio.to_thread`) had no deadline — a hung relay froze the
   withdrawal/sweep coroutine forever. Now bounded by
   `RELAYER_CALL_TIMEOUT_SECONDS` (default 180s); expiry propagates as the
   existing post-broadcast AMBIGUOUS failure (deliberately NO auto-refund —
   the relayer may already have broadcast; operator reconciles).
6. **cset market loader resilience** (`services/signal_scan/signal_scan_job.py`)
   — `asyncio.gather(..., return_exceptions=True)`: one failed market lookup
   now drops that market (logged per-id) instead of aborting the whole
   complete-set pass for the user-tick. Plus `state/WORKTODO.md` mojibake
   repair (`"钒`/`−` → `↓` in the P0 spine diagram; encoding drift per
   AGENTS.md ENCODING RULE).

New config: `POLYGON_RPC_TIMEOUT_SECONDS=20`, `RELAYER_CALL_TIMEOUT_SECONDS=180`
(both env-tunable, both with stub-Settings `getattr` back-compat).

## 2. Current system architecture (verified runtime data flow)

Audited from code by 5 parallel adversarial sweeps + direct verification of
every capital-path claim. The locked pipeline holds in code:

```text
DATA          integrations/polymarket.py (Gamma + CLOB reads, tenacity retry,
              rate limiters) -> jobs/market_sync (60s) -> markets table
              integrations/polygon.py (deposit watcher chain reads)  <- HARDENED
STRATEGY      domain/strategy/strategies/{late_entry_v3,weather,playbook}.scan()
              -> SignalCandidate; orchestrated by
              services/signal_scan/signal_scan_job.run_once / run_close_sweep_fast
INTELLIGENCE  oracle edge/distance observation (advisory; hard-reject gate
              fail-open by owner design #1726 when oracle off) + EV scorer
              (PARKED, WARP-78)
RISK          domain/risk/gate.py evaluate() — 13 steps; ALL entry points
              (TradeEngine, copy-trade, weather, playbook, late_entry_v3)
              route through services/trade_engine/engine.execute() -> gate.
              NO bypass path found (3 independent passes).
EXECUTION     domain/execution/router.py -> paper.py | live.py;
              live: 8-guard chain (router + assert_live_guards x2 + per-user
              wallet-identity assert in-claim-transaction), idempotency claim
              INSERT ON CONFLICT BEFORE submit, ambiguous-submit -> 'unknown'
              + operator page; close: atomic 'closing' claim.
              Reconcile mesh: lifecycle poller (submitted/pending/partial) +
              live_reconcile ('unknown' adoption + stranded 'closing') +
              complete_set reconciler.
MONITORING    structlog -> Fly logs -> Sentry (ERROR+); audit.write on every
              capital action; portfolio snapshots -> pg NOTIFY -> WebTrader SSE;
              TradeNotifier paper/live parity (#1755).
```

Scheduler: ~40 APScheduler jobs, all `max_instances=1, coalesce=True`, single
AsyncIO loop. The two genuinely-unbounded network boundaries (Polygon RPC,
relayer SDK) are now bounded; CLOB calls already run behind breaker+limiter.

## 3. Files created / modified

- projects/polymarket/crusaderbot/integrations/polygon.py (timeout, retry
  predicate, `_rpc_deadline`, adaptive `scan_from_cursor`)
- projects/polymarket/crusaderbot/scheduler.py (`watch_deposits` cursor-read
  stage; `_watch_deposits_failed(**context)`, `repr(exc)` on both levels)
- projects/polymarket/crusaderbot/wallet/custody.py (relayer deadlines)
- projects/polymarket/crusaderbot/config.py (two new settings)
- projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py
  (cset gather `return_exceptions` + per-market failure log)
- projects/polymarket/crusaderbot/tests/test_rpc_watcher_hardening.py (NEW —
  13 hermetic tests)
- projects/polymarket/crusaderbot/state/WORKTODO.md (mojibake repair +
  timestamp)
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md,
  projects/polymarket/crusaderbot/state/CHANGELOG.md (lane sync)
- projects/polymarket/crusaderbot/reports/forge/rpc-watcher-hardening.md (this
  report)

## 4. What is working (audit verdicts — evidence-based)

**Runtime evidence this session:** 13 new tests green; 103 touched-surface
regression tests green (watcher rescue/deposit e2e/reorg/native decode/
watcher-wallet/sweep/custody/withdraw-flow/cset-scan); full suite result in
§6; ruff clean on all touched files. The watcher's exact eth_getLogs request
shape (1000-block span, transfer topic, padded to-address OR-array) was
replayed against a vanilla public Polygon node from this container and
**accepted** — proving the request encoding is valid JSON-RPC and the prod
failure is provider-plan/transport behavior, which this lane's adaptive range
+ retry widening + deadlines close in all deterministic variants.

**Risk constants (re-verified in code, all PASS):** Kelly clamp 0.25
(domain/risk/gate.py:654-663), position cap <=10% (domain/risk/constants.py),
daily loss -$2,000 (constants + effective_daily_loss), drawdown >8% halt
(gate step 6), liquidity floor $10,000 (gate step 11), dedup (idempotency key
+ market dedup, step 10), kill switch fail-safe-to-halt (domain/ops/
kill_switch.py — DB error returns True=halted), per-user concurrent
(5/12/20/override, no global ceiling, gate step 7).

**Adjudicated clean (subagent claims I re-verified against code and REJECTED):**
- "Per-user wallet cache staleness can sign with wrong wallet" — FALSE: the
  identity assert reads `wallets.polymarket_deposit_wallet` on the SAME
  connection/snapshot as the idempotency claim and compares against the
  cached SDK resolution — drift FAILS CLOSED (refuses), never signs
  (domain/execution/live.py:269-295, per_user_clob.py).
- "Oracle hard-reject default True is a critical footgun" — working as
  designed: fail-open only on non-`computed` verdicts is the owner-approved
  #1726 design; zero behavior change with oracle off.
- "Float shares = ledger drift" — ledger debits `size_usdc` as Decimal;
  shares float noise is sub-tick and never enters the ledger (LOW follow-up
  only).
- "Step-3 persist failure orphans broker order silently" — order row stays
  'pending'; the lifecycle poller pages the operator via
  `_mark_stale("missing polymarket_order_id")` (lifecycle.py:201-208) and the
  failure itself audits `live_post_submit_db_error` + raises
  LivePostSubmitError (no paper-fallback). Non-silent; page-wording
  improvement filed as FOLLOW-UP.

**Four-surface readiness (paper | live):**
- Backend/Polymarket integration: READY | code-READY (owner ops remain:
  sidecar/per-user flags + 5-guard flip; broker proof PASS run #7).
- Wallet + strategy execution: READY | gate-4 deposit detection was the
  blocker — this lane makes the watcher self-healing + diagnosable; ledger /
  withdrawal / sweep paths verified with refund-on-preflight + ambiguous
  posture intact, now hang-proof.
- WebTrader frontend: READY | READY — no critical findings; gate labels
  pinned to backend GATE_ORDER; admin endpoints role-gated + rate-limited;
  XSS/SQLi clean; SSE token scope-segregated.
- Telegram bot: READY | READY — live-truth lanes #1755/#1756 verified in
  code; notifications retry with 429 honor; global error handler present.

## 5. Known issues (adjudicated, prioritized — BLOCKER vs FOLLOW-UP)

**BLOCKER (live go-live only; none are code defects in this repo today):**
- Gate 4 deposit detection in PROD is owner-ops sequenced: deploy this lane →
  read the now-context-rich `watch_deposits` line if any tick still fails
  (one log line now names stage + cursor + head + watched + lookback +
  repr(err)) → run admin "Backfill deposit wallets" (#1758; 6 rows NULL,
  prod-verified this session) → ensure the funding deposit falls within
  `DEPOSIT_SCAN_LOOKBACK_BLOCKS` (~28h at 50k; raise once via env if older).
  No further code gap is identifiable from the repo: request shape proven
  valid against a vanilla node; all deterministic provider-cap variants now
  self-heal via adaptive range.

**FOLLOW-UP (open, ranked; none capital-destroying):**
1. [HIGH / MAJOR] Stale live order page wording + adoption: a live order
   stranded 'pending' with no broker id (submit ok + immediate DB failure)
   pages `order_stale: missing polymarket_order_id` but does not say "check
   broker for a resting order — possible untracked exposure"; extend
   live_reconcile adoption sweep (currently 'unknown' only) to cover it.
   domain/execution/lifecycle.py:201-208, live_reconcile.py.
2. [MED / MAJOR] Crash-recovery resume can use a cached/0.5-fallback price
   while a comment claims prices are re-fetched at resume; add a live price
   re-fetch before `router_execute` on the resume path + fix the comment.
   services/signal_scan/signal_scan_job.py:2722-2834.
3. [MED / MAJOR] Ledger idempotency backstop: UNIQUE(ref_id, type) +
   ON CONFLICT guard (today callers guarantee idempotency via status guards —
   add the schema net). wallet/ledger.py + migration.
4. [MED / STANDARD] live.execute dry-run returns before the slippage guard
   computes — fine for capital (no broker call possible) but hides guard
   verdicts during rehearsal; reorder or log the would-be verdict.
   domain/execution/live.py:147-157.
5. [MED / STANDARD] Admin paper-reset: add typed-confirm + 2FA re-check
   (irreversible bulk delete, currently one admin click; audited).
   webtrader backend router paper-reset handler.
6. [LOW / STANDARD] execution_queue INSERT conflict after engine-approve is
   logged "accepted" — log distinct outcome. signal_scan_job.py:3326-3360.
7. [LOW / STANDARD] Decimal-quantize live shares before submit (cosmetic
   precision; ledger unaffected). domain/execution/live.py:151/239/506.
8. [LOW / STANDARD] SSE stream-token: revoke prior token on re-mint or drop
   TTL 60s→15s. api stream-token handler.
9. [LOW / MAJOR-when-done] Per-job `asyncio.timeout` wrappers for the
   remaining network-bound scheduler jobs (CLOB-bound jobs already sit behind
   breaker+limiter; polygon/relayer — the two proven wedges — are closed by
   this lane).
10. [LOW / MINOR] WORKTODO.md content is stale vs PROJECT_STATE (P0 lists
    from May; F-HIGH-2 open item superseded by later lanes) — needs a CMD
    review pass, not blind regeneration. Mojibake fixed this lane.

**Edge cases explicitly covered by the new tests:** provider rejects every
span (floor reached → reraise, no infinite halving); transport error during
scan (no halving, fail-fast, next tick retries); hung RPC bounded even with
retry layer active; cursor-read DB blip counted into the DOWN streak; hung
relayer bounded with happy path byte-identical; one bad cset market doesn't
kill the pass; stub-Settings without the new fields keep working.

## 6. What is next

1. Merge on CI green (WARP•R00T full bypass; inviolable invariants untouched —
   risk constants / Kelly / guards / kill switch / secrets / asyncio-only all
   byte-unchanged, verified by suite + grep).
2. Owner ops (mobile-runnable): deploy → watch `watch_deposits` (expect cursor
   to move off 0 within ~2 min; if not, the single ERROR line now contains
   everything needed) → admin Backfill button → confirm $8.32 deposit credits
   → gate 4 flips → proceed with the documented guard-flip sequence.
3. FOLLOW-UP lanes in §5 order (1 → 5 first; each is half-day scoped).

**Refactoring strategy (deliberate):** no rewrites — every fix is a bounded
insertion at an existing seam (provider construction, retry predicate, one
loop, one try/except, two wait_for wraps). The reconcile mesh, gate, and
ledger semantics were left byte-identical; improvements there are scoped
follow-up lanes, not opportunistic edits inside a hardening lane.

**Production-grade improvement plan (beyond follow-ups):** persist watcher
health (last-success timestamp) for a /health surface + restart-surviving
escalation; provider-agnostic RPC failover (second RPC URL, round-robin on
permanent failure); job-level watchdog that pages when any interval job
misses 3 consecutive expected runs (catches the entire wedge class, not just
known boundaries).

## Validation evidence

- NEW: tests/test_rpc_watcher_hardening.py — 13 passed.
- Regression (touched surfaces): 103 passed (watch_deposits_rescue,
  deposit_e2e, deposit_reorg, polygon_native_decode, watcher_deposit_wallet,
  sweep_deposits, custody_safe, wallet_withdraw_flow, complete_set_scan).
- Full suite: see PROJECT_STATE entry (run from repo root via pytest.ini).
- ruff: clean on all touched files.
- Prod (read-only Supabase): chain_cursor both rows block 0 (seeds), deposits
  empty, wallets 6/6 deposit_address, 0/6 polymarket_deposit_wallet —
  matching and extending the #1753/#1758 evidence.
- Live RPC replay: watcher getLogs shape accepted by vanilla public node;
  Alchemy demo endpoint returns bare HTTP 429 (ClientResponseError class —
  the exact retry-predicate gap fixed here).
