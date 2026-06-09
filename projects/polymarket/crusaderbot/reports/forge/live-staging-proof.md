# WARP-74 Lane 2 — Live-Reconcile Staging Proof Harness

- Validation Tier: STANDARD (test harness + operator docs + state; zero production code change)
- Claim Level: NARROW INTEGRATION (real-broker harness scaffolding; execution waits on operator wallet)
- Validation Target: an executable, CI-safe staging harness + runbook covering all 5 WARP-74 acceptance cases, ready to run the moment an isolated staging wallet is provisioned
- Not in Scope: provisioning the staging wallet, executing the harness against a live broker, any change to domain/services/bot/Fly/Supabase, flipping ENABLE_LIVE_TRADING
- Suggested Next Step: WARP🔹CMD provisions the throwaway wallet + funds minimal USDC, runs the harness per the runbook, files evidence, then makes the LIVE go/no-go call

## 1. What was built

A live-broker staging proof for the three P0 reconcile gaps merged in #1613. The
hermetic suite (`tests/test_live_reconcile.py`) already proves the routing logic
with fakes; this harness proves the same logic against a **real Polymarket CLOB
broker** on an **isolated throwaway wallet** with **tiny orders** — the one thing
fakes cannot show (a real `cancel_all` pulling a resting GTC off-chain, real
`get_open_orders` truth driving adoption, drift detection seeing a real orphan).

- `tests/staging/test_live_reconcile_staging.py` — parametrized harness, all 5
  acceptance cases, guarded by `STAGING_WALLET_KEY` (skips cleanly with no wallet).
- `docs/runbooks/warp74-staging-proof.md` — operator runbook: prereqs, env-var
  matrix, per-case steps, expected Telegram alert text, PASS/FAIL criteria,
  4-artifact evidence capture, teardown.
- State files updated (incl. the WARP-72 scorer-parking note folded in).

Design choice: only the **broker** is real. The DB side of every test is an
in-memory recording fake, so the harness **never writes a database** — it cannot
touch prod Supabase even by misconfiguration. Each test places only its own
resting orders and cancels them on teardown (fully independent, no shared state).

## 2. Current system architecture

```
tests/staging/test_live_reconcile_staging.py
  guard:  pytest.mark.skipif(not STAGING_WALLET_KEY)        # inert in CI
  client: _staging_settings() -> ensure_clob_credentials -> get_clob_client (REAL)
  broker fixture (persistent, places+verifies+cancels)  ||  _factory (throwaway,
                                                            handed to functions
                                                            under test which aclose it)
  DB:     _Pool/_Conn recording fake (no real DB writes, ever)
  pages:  monkeypatch notifications.notify_operator -> capture alert text

  Case 3  -> kill_switch_exec._broker_cancel_all_orders   (real GTC must be GONE)
  Case 2  -> live_reconcile.reconcile_live_orders          (adopt / page / halt)
  Case 1  -> live_reconcile.reconcile_closing_positions    (rollback / page / finalize*)
  Case 4  -> drift_detector.detect_order_drift             (broker-only + db-only, no mutation)
  Case 5  -> execution.router.execute                      (infra-degraded -> paper + alert)
                                                            (* fill-gated by STAGING_ALLOW_FILLS)
```

Nothing under `domain/`, `services/`, or `bot/` was modified — the harness drives
the already-merged WARP-74 functions through their public signatures
(`pool=`, `clob_factory=`, `settings=`) exactly as the scheduler does.

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/tests/staging/__init__.py`
- `projects/polymarket/crusaderbot/tests/staging/test_live_reconcile_staging.py`
- `projects/polymarket/crusaderbot/docs/runbooks/warp74-staging-proof.md`
- `projects/polymarket/crusaderbot/reports/forge/live-staging-proof.md`

Modified (state only):
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/WORKTODO.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

- `pytest tests/staging/ -q` with no `STAGING_WALLET_KEY` → **9 skipped, 0
  failures** (verified). CI posture is safe: collects, skips, never networks.
- `py_compile` clean; `ruff check tests/staging/` → all checks passed.
- Each of the 5 cases asserts against real broker truth (the deterministic,
  non-fill parts) plus the exact operator alert string from the merged code:
  Case 3 (GTC gone), Case 2 (adopt/mismatch/halt), Case 1 (rollback/page-no-id),
  Case 4 (broker-only + db-only, zero DB mutation), Case 5 (LIVE INFRA DEGRADED
  → paper).

## 5. Known issues

- The harness is **build-only** until the operator provisions an isolated staging
  wallet + minimal USDC. Until then every test skips — this is intended, not a gap.
- `finalize-once` / `page-partial` require a **real fill** (real USDC), so they are
  additionally gated by `STAGING_ALLOW_FILLS=1` + an operator-produced
  `STAGING_FILLED_CLOSE_ID`; otherwise they skip.
- Resting-order non-fill safety depends on the operator picking a market trading
  **above** `STAGING_REST_PRICE` (documented in the runbook prereqs).

## 6. What is next

1. WARP🔹CMD provisions the throwaway wallet, funds minimal USDC, exports the
   `STAGING_*` env on a **separate** staging app/shell (never prod).
2. Run the harness per `docs/runbooks/warp74-staging-proof.md`, capture the
   4-artifact evidence bundle per case.
3. File evidence; WARP🔹CMD makes the `ENABLE_LIVE_TRADING` go/no-go decision.

---

Tier: STANDARD → WARP🔹CMD review required (no SENTINEL — harness + docs + state
only, zero production code change). Source: this report.
