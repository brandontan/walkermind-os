# WARP•SENTINEL REPORT — order-lifecycle (REVISED)

PR: #913 — Phase 4C order lifecycle
Branch: WARP/CRUSADERBOT-PHASE4C-ORDER-LIFECYCLE
Forge report: projects/polymarket/crusaderbot/reports/forge/order-lifecycle.md

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Environment: dev (local validation)

---

## VERDICT: **BLOCKED**

Score: **N/A** (Phase 0 fail — test suite red at HEAD).
Critical issues: **1** (test suite has 5 failing tests at PR HEAD, plus a derived correctness concern on cancel/expiry refund math).

This report **supersedes** the prior APPROVED 96/100 verdict (commit `005c55a`).
The prior verdict was rendered against PR head `6b2552c` and is no longer
valid because runtime code has materially changed.

---

## AUDIT BASELINE NOTE (CRITICAL)

The original audit was performed against PR head `6b2552c`. While that
report was being committed, two new commits landed on the branch:

- `bed7c70` — `fix(adapter): get_fills uses supported filters + client-side match (Codex P1, part 1/3)`
- `18de386` — `fix(lifecycle): drop paper synthesis, derive fills from get_order (Codex P1, part 2/3)`

These commits are responses to Codex review and are **functionally an
improvement** (they fix a real CLOB API limitation and remove a paper-mode
shortcut that could corrupt state if the operator toggled `USE_REAL_CLOB`
off mid-flight). However, they are labelled "part 1/3" and "part 2/3" — the
implied "part 3/3" (test updates) **has not landed**.

The result: the test fixtures still mock the OLD lifecycle contract
(`client.get_fills` calls, paper-mode synthesis, `taker_order_id=` URL),
which the runtime no longer matches. The suite is red.

---

## 1. TEST PLAN (re-run)

```
$ pytest projects/polymarket/crusaderbot/tests/test_order_lifecycle.py -q
5 failed, 24 passed, 7 warnings
```

PR head at audit: `005c55a` (tip — includes my prior approval commit).
Runtime code under test: `lifecycle.py` + `adapter.py` at `18de386` / `bed7c70`.

---

## 2. CRITICAL ISSUES

### CRIT-1 — Test suite red at PR HEAD (5 failing tests)

Cited verbatim from `pytest --tb=short` output:

1. `test_paper_mode_synthesises_fill_after_one_cycle`
   - Cause: `PAPER_FILL_AFTER_ATTEMPTS` constant + paper synthesis branch
     deleted in `18de386` (was `lifecycle.py:159-170` previously).
   - Test still asserts a synthetic fill was written
     (`tests/test_order_lifecycle.py:260-279`).
   - Failure: `assert out["filled"] == 1` — sweep now returns
     `out["open"] == 1` instead.

2. `test_live_filled_writes_fills_and_notifies`
   - Cause: lifecycle now derives fills from `client.get_order()` payload
     via `_broker_fills(broker, order)`; `client.get_fills(...)` is no
     longer awaited.
   - Test asserts `client.get_fills.assert_awaited_with("brk-fill-1")`
     (`tests/test_order_lifecycle.py:324`).
   - Failure: `AssertionError: Expected await: get_fills('brk-fill-1')
     Not awaited`.

3. `test_live_cancelled_rolls_position_back`
   - Same root cause as #2 — `client.get_fills.assert_awaited()` at
     `tests/test_order_lifecycle.py:358`.
   - Failure: `AssertionError: Expected get_fills to have been awaited.`

4. `test_live_cancelled_partial_fill_resizes_position_and_refunds_remainder`
   - Cause: test mocks `client.get_fills` to return a 50-share partial
     fill; lifecycle no longer calls `client.get_fills`. Instead,
     `_broker_fills(broker, order)` reads `size_matched` from the
     `client.get_order()` payload — which the test mocks as
     `{"status": "cancelled"}` with no `size_matched`. So `_broker_fills`
     returns `[]`, refund math falls through to "no fill" branch, and
     the user is credited the full $100 instead of the expected $80.
   - Failure: `AssertionError: assert Decimal('100.0') == Decimal('80.0000')`.
   - **This is a real-runtime correctness concern, not just a test
     fixture drift** — see CRIT-2.

5. `test_adapter_get_fills_normalises_envelope`
   - Cause: `bed7c70` changed adapter URL from
     `/data/trades?taker_order_id=BRK-1` to
     `/data/trades?maker_address={signer}` plus client-side filter.
   - Test asserts `"/data/trades?taker_order_id=BRK-1" in str(seen[0].url)`
     (`tests/test_order_lifecycle.py:737`).
   - Failure: assertion error on URL substring.

### CRIT-2 — Possible refund-math regression on cancel/expiry (derived from CRIT-1 #4)

`_broker_fills(broker_payload, order)` returns `[]` when `size_matched`
is missing/zero on the `/data/order/{id}` payload — `lifecycle.py:680-685`
in the new code (`18de386`). The cancel/expiry path then computes
`refund = size_usdc - 0 = size_usdc` and, if a position exists, credits
the full notional back. This is correct ONLY when the broker reliably
populates `size_matched` on cancel/expiry payloads.

If a partial-fill-then-cancel ever returns a payload **without**
`size_matched`, the user keeps both the matched shares **and** receives a
full USDC refund — the exact double-credit that commits 4a94acd + a995d52
were written to prevent.

Required mitigation before APPROVED can be re-issued:
- Either restore the `client.get_fills(broker_id)` call in the cancel/expiry
  path (with the new adapter implementation that uses `maker_address` +
  client-side match), OR
- Document and prove that the broker `/data/order/{id}` payload reliably
  includes `size_matched` on terminal status responses, with a hermetic
  test using a fixture that mirrors the real broker shape.

---

## 3. WHAT IS STILL PASSING

- 24/29 lifecycle tests pass (helpers, prefix-strip, stale guard,
  open-status touch, race-loss skip, factory-failure abort, mock-client
  surface, scheduler registration).
- Migration 015 idempotency — code unchanged from audited baseline.
- APScheduler `order_lifecycle` job concurrency
  (`max_instances=1, coalesce=True`) — code unchanged.
- Activation guards: `USE_REAL_CLOB` default `False` preserved; the new
  paper-mode branch is more conservative (touches the row instead of
  synthesising a fill — eliminating a state-corruption vector).
- Phase 4A regression: not re-run after `bed7c70`. Re-run required if
  adapter changes are intended to preserve 4A surface.

---

## 4. STABILITY SCORE

Not computed. Phase 0 fails on test-suite red — verdict is BLOCKED by
fiat per SENTINEL rule "Implementation evidence exists for critical
layers -> else BLOCKED". Tests ARE the implementation evidence and they
are red.

---

## 5. GO-LIVE STATUS

**BLOCKED** — recommend NOT merging until:

1. The implied "part 3/3" test-update commit lands and the suite goes
   green at PR HEAD.
2. CRIT-2 (cancel/expiry refund math against payloads missing
   `size_matched`) is resolved either by restoring `client.get_fills` for
   cancel/expiry or by proving broker payload reliability with a fixture
   test.

---

## 6. FIX RECOMMENDATIONS

Priority P0 (blocker — required before merge):

1. **Push the "part 3/3" test update**. Specifically, the following
   tests need to be rewritten against the new contract:
   - `test_paper_mode_synthesises_fill_after_one_cycle` →
     replace with a test asserting paper mode TOUCHES the row instead
     (returns "open", increments `poll_attempts`).
   - `test_paper_mode_does_not_call_broker` — verify still passes
     (factory should still never be called).
   - `test_live_filled_writes_fills_and_notifies` — drop the
     `client.get_fills.assert_awaited_with(...)` assertion; assert
     fills derived from the `get_order` payload instead. Include a
     `size_matched` field in the mocked broker payload.
   - `test_live_cancelled_rolls_position_back` — drop
     `client.get_fills.assert_awaited()`; switch to asserting on the
     `_broker_fills` aggregate behavior.
   - `test_live_cancelled_partial_fill_resizes_position_and_refunds_remainder`
     — restructure to mock `client.get_order` returning
     `{"status": "cancelled", "size_matched": 50, "price": 0.40}` so
     the new `_broker_fills` path produces the same $20 matched / $80
     refund as before.
   - `test_adapter_get_fills_normalises_envelope` — assert on the new
     `/data/trades?maker_address={signer}` URL and add a client-side
     filter case for trades whose taker/maker order id matches.
   - Add explicit coverage for the new `_broker_fills` helper:
     zero-`size_matched`, missing-`size_matched`, malformed price,
     partial-fill aggregate.

2. **Resolve CRIT-2** — either restore `client.get_fills` for the
   cancel/expiry branch (using the new `bed7c70` adapter implementation),
   or provide a fixture-grounded proof that `/data/order/{id}` reliably
   includes `size_matched` on terminal status payloads.

Priority P1 (nice to have, post-fix):

3. Add a regression test that simulates "broker payload missing
   `size_matched` on cancel" → assert refund is NOT full notional, OR
   that an operator alert fires. This guards against future broker
   schema drift.

---

## 7. DONE OUTPUT

```
Done -- GO-LIVE: BLOCKED. Score: N/A. Critical: 1 (test-suite red, refund regression risk).
PR: WARP/CRUSADERBOT-PHASE4C-ORDER-LIFECYCLE
Report: projects/polymarket/crusaderbot/reports/sentinel/order-lifecycle.md (REVISED — supersedes 005c55a APPROVED)
State: PROJECT_STATE.md updated to BLOCKED
NEXT GATE: Push "part 3/3" test updates + resolve CRIT-2; then re-audit.
```
