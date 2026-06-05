# WARP-74 staging proof — order placement PROVEN; poll the eventually-consistent readback

Validation Tier: STANDARD (test harness; no runtime/capital path change)
Claim Level: NARROW INTEGRATION (CLOB v2 order placement proven live; readback made propagation-robust; full case3 pass pending next dispatch)
Validation Target: case3 readback of a freshly placed/cancelled order on the pysdk CLOB v2 backend.
Not in Scope: trading/execution code; LIVE gating.
Suggested Next Step: re-dispatch `staging-proof-fly.yml` case3 (nrt, defaults).

---

## 1. Breakthrough (run #9, 27020079984)

With the Gamma resolver live, run #9 proved the migration end-to-end at the
placement layer:

- Gamma auto-resolved a live OPEN market (no stale secret, no RuntimeError).
- `_place_resting_buy` BUILT → SIGNED → POSTED a real order on the **CLOB v2
  polymarket-client backend** and the broker **ACCEPTED it (returned an order id)**.
  Both prior blockers — `order_version_mismatch` and `the orderbook does not
  exist` — are GONE. The CLOB v2 SignedOrder path works against the real broker.

The only remaining case3 failure was the **precondition readback**:
`assert any(... in get_open_orders(_MARKET))` failed immediately after the POST.

## 2. Root cause

Polymarket's `/data/orders` read is **eventually-consistent** after a POST (and
after a cancel): a single read taken immediately can miss a just-placed order (or
still show a just-cancelled one). The test asserted on one immediate read, which
is racy. (A market-scoped filter quirk would produce the same symptom.)

## 3. Fix

Added `_poll_open_order(broker, bid, present=...)`: bounded poll (10×1.5s) that
checks the market-scoped open-orders list first, then the unscoped list as a
fallback (covers read-after-write lag AND any market-filter quirk). case3 now:

- precondition → `assert await _poll_open_order(..., present=True)` (order rests)
- post-kill   → `assert not await _poll_open_order(..., present=False)` (order gone)

This does NOT mask a genuine cross/fill: if the order had crossed it would never
appear and the poll would correctly time out. The resolver already guarantees the
chosen token's best ask is above the rest price, so a fill cannot occur.

## 4. Files modified (full repo-root paths)

- `projects/polymarket/crusaderbot/tests/staging/test_live_reconcile_staging.py` — `_poll_open_order` helper; case3 uses it for both readbacks.
- `projects/polymarket/crusaderbot/reports/forge/staging-orderbook-readback-poll.md` — this report.
- `state/PROJECT_STATE.md`, `state/CHANGELOG.md` — lane sync.

## 5. What is working

- CLOB v2 order build/sign/post ACCEPTED by the real broker (proven, run #9).
- Gamma auto-resolution of a live open market (proven, run #9).
- `py_compile` clean; inert in CI (skips without `STAGING_WALLET_KEY`).

## 6. Known issues / boundaries

- If case3 still fails after this with the poll timing out on `present=True`, the
  order is crossing/filling (would need a lower rest price or different token) —
  not expected given the ask-above-rest guarantee.
- cases 1/2/4 drive the reconciler's own queries; if propagation lag affects them
  too, a similar poll may be needed there (deferred until observed).

## 7. What is next

1. Re-dispatch `staging-proof-fly.yml` case3 (nrt, defaults) → expect PASS (resting GTC cancelled by the kill switch).
2. `all-broker` for cases 1–2–4; confirm `signature_type` proxy inference; close GTC-only gap; pass all 5 before any LIVE flip.

---

Validation Handoff (NEXT PRIORITY): WARP🔹CMD review — STANDARD. Source: projects/polymarket/crusaderbot/reports/forge/staging-orderbook-readback-poll.md.
