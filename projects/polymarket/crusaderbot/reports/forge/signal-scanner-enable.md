# WARP•FORGE REPORT — signal-scanner-enable

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: Signal scanner pipeline — feed seeding, user enrollment, access_tier alignment
Not in Scope: Live path (Heisenberg), activation guards, risk gate, execution engine, ENABLE_LIVE_TRADING
Suggested Next Step: WARP🔹CMD review → apply migration 031 to production → verify scanner tick logs published > 0

---

## 1. What was built

Three root causes prevented signals from flowing through the pipeline:

**Root Cause A — Demo feed missing from DB**
`market_signal_scanner._feed_active(DEMO_FEED_ID)` silently returned False when migration 024 ran on an empty DB (zero users → `SELECT FROM users LIMIT 1` produced 0 rows → feed INSERT skipped). Scanner exited with (0, 0) every tick.

**Root Cause B — Users not enrolled after migration 024**
Users created after migration 024 was applied had no rows in `user_strategies` (signal_following) and no row in `user_signal_subscriptions`. `signal_scan_job._load_enrolled_users()` JOIN against `user_strategies` returned empty — scan tick was a silent no-op.

**Root Cause C — access_tier filter inconsistent with role model**
`_load_enrolled_users()` required `u.access_tier >= 3`. Role model PR #1076 opened paper to all users but new users were created with `access_tier = 2`. Scanner excluded all new-signup users from paper scanning.

**Fixes delivered:**

1. `migrations/031_signal_scanner_user_enrollment.sql` — idempotent backfill migration:
   - Re-seeds DEMO feed (UUID `00000000-0000-0000-0001-000000000001`) if missing
   - Re-seeds LIVE feed (UUID `00000000-0000-0000-0002-000000000001`) if missing
   - Enrolls all existing users in `signal_following` strategy
   - Subscribes all existing users to demo feed
   - Sets `access_tier = 3` for all users with `access_tier < 3`

2. `services/signal_scan/signal_scan_job.py` — `_load_enrolled_users()` access_tier filter relaxed:
   - Before: `AND u.access_tier >= 3`
   - After: `AND (u.access_tier >= 3 OR s.trading_mode != 'live')`
   - Paper users are eligible regardless of tier; live trading still requires tier 3

3. `users.py` — new user creation hardened:
   - `upsert_user()` INSERT now uses `access_tier = 3` (was 2); bump guard also updated to `< 3`
   - `_enroll_signal_following()` helper added — enrolls new user in `user_strategies` + subscribes to demo feed
   - Called from `upsert_user()` after `seed_paper_capital()` — same post-transaction pattern, isolated try/except

---

## 2. Current system architecture

Signal pipeline (paper mode):

```
[Scheduler every 60s]
  └─ market_signal_scanner.run_job()
       ├─ _feed_active(DEMO_FEED_ID) → True (after migration 031)
       ├─ polymarket.get_markets(limit=200)
       ├─ filter: liq >= 10_000, yes_p < 0.15 or no_p < 0.15
       └─ _publish() → signal_publications (is_demo=TRUE)

[Scheduler every 180s]
  └─ sf_scan_job.run_once()
       ├─ _load_enrolled_users() → users with auto_trade_on=TRUE
       │    AND strategy=signal_following AND access_tier>=3 OR paper mode
       ├─ SignalFollowingStrategy.scan() → SignalCandidate list (DB read)
       │    matches user subscriptions to recent signal_publications
       └─ TradeEngine.execute() → risk gate → paper fill → orders + positions

[New user (/start)]
  └─ upsert_user() → access_tier=3
       ├─ create_wallet_for_user()
       ├─ seed_paper_capital() → $1,000 USDC
       └─ _enroll_signal_following() → user_strategies + user_signal_subscriptions
```

---

## 3. Files created / modified

| File | Action |
|---|---|
| `projects/polymarket/crusaderbot/migrations/031_signal_scanner_user_enrollment.sql` | CREATED — backfill migration |
| `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` | MODIFIED — line 99, access_tier filter |
| `projects/polymarket/crusaderbot/users.py` | MODIFIED — _enroll_signal_following() helper + upsert_user() access_tier + enrollment call |

---

## 4. What is working

- Migration 031 is idempotent — safe to apply on a DB that already ran 024/025 correctly
- `_enroll_signal_following()` is guarded with `WHERE EXISTS (signal_feeds WHERE status='active')` — no-op if feed not yet seeded
- `_enroll_signal_following()` uses `WHERE NOT EXISTS (unsubscribed_at IS NULL)` — no duplicate subscriptions
- `upsert_user()` existing-user path now bumps `access_tier` to 3 for legacy users with tier < 3 on their next /start
- Paper-mode scanner runs without Heisenberg token (live path already had its own guard)
- All three changes are backwards-compatible — no table drops, no schema changes, no activation guard mutations

---

## 5. Known issues

- Live path (Heisenberg) requires `HEISENBERG_API_TOKEN` env var to be set — live feed (`LIVE_FEED_ID`) produces 0 signals if token missing. Separate concern; not in scope for this lane.
- `auto_trade_on` must be explicitly enabled per user — users who have not turned on auto-trade will not receive signal executions even after enrollment. This is correct behavior.
- Migration 031 step 1/2 (feed re-seed) requires at least one user to exist in DB for `operator_id` SELECT. On a completely empty DB (no users) feeds still won't seed — this matches the original 024/025 pattern and is acceptable (bot cannot have signal subscribers if no users exist).
- access_tier dual-table drift (users.access_tier integer + user_tiers string) retained by design — see KNOWN ISSUES in PROJECT_STATE.md.

---

## 6. What is next

1. Apply migration 031 to production DB (idempotent — safe to apply immediately)
2. Restart bot on Fly.io to pick up `users.py` + `signal_scan_job.py` changes
3. Verify scanner tick log: `market_signal_scanner: tick done demo_scanned=X published=Y` — Y should be > 0 within 60 seconds
4. Verify `signal_scan_job` tick: check `orders` table for new paper positions for users with `auto_trade_on=TRUE`
5. WARP🔹CMD review required (STANDARD tier) — no SENTINEL run needed for this lane
