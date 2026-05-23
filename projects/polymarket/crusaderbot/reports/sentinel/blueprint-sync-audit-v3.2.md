# SENTINEL AUDIT — Blueprint-Code Sync v3.2

**Audit date:** 2026-05-23 15:30 Asia/Jakarta
**Repo HEAD SHA:** `1afba00eb55dfa0c20e12e0dc26976b1c92df921`
**Blueprint version audited:** v3.2 (`docs/blueprint/crusaderbot.md`, commit `1afba00`, stamped 2026-05-23 15:30)
**Auditor:** WARP•SENTINEL
**Linked issue:** WARP-41 (exists in Linear `W.A.R.P ENGINE`, confirmed via MCP)

---

## 1. Summary

### Severity totals

| Severity | Count |
|---|---|
| CRITICAL | 0 |
| MAJOR | 11 |
| MINOR | 12 |
| NIT | 4 |

### Verdict

**BLUEPRINT-DRIFT-MAJOR** — multiple MAJOR findings, zero CRITICAL. All live-trading activation guards are OFF and the system runs PAPER only, so no MAJOR finding reaches a live money-handling path at HEAD.

### Headline issues

- **§11 Database Schema is the most drifted section (MAJOR):** ~13 of the ~34 claimed table names do not match the actual schema (e.g. `ledger_entries`→`ledger`, `risk_decisions`→`risk_log`, `user_trade_settings`→`user_settings`, `fee_records`→`fees`/`fee_config`, `referral_links`→`referral_codes`, `wallet_leaderboard`→`leaderboard_stats`). Several claimed tables are absent (`sub_accounts`, `withdrawals`, `proxy_wallet_pool`, `auto_trade_state`, `pnl_daily`, `user_market_filters`, `referral_earnings`). Actual table count at HEAD is ~43, not 34.
- **§11 internal contradiction (MAJOR):** the `users` tuple still lists `access_tier` (`docs/blueprint/crusaderbot.md:626`) even though §1 and §1b state it was dropped in migration 044.
- **Audit-log append-only is unrealized (MAJOR, safety-relevant):** §5/§11 claim a physically-separate, INSERT-only audit DB; actual `audit_log` is a single-DB table (`migrations/033_risk_caps_audit_log.sql:10`) with an `updated_at` column and no REVOKE/trigger enforcing append-only. §1b documents this as a deferred gap. Surfaced per escalation rule; not CRITICAL because guards are OFF and the gap is documented.
- **§6 risk gate composition drift (MAJOR):** blueprint claims a 13-step gate with `tenant_scope`/`live_mode`/`capital_mode`/`cost` steps; code (`domain/risk/gate.py`) runs steps 0–14 with different composition (adds role, strategy-availability, market-impact; no discrete tenant/capital/cost steps). All 13 hard-wired risk **constants** match code exactly.
- **Fee model drift (MAJOR):** blueprint says 1% fee with 80/20 admin/referrer split; code uses 10% (`services/fee/fee_service.py:22-27`, seeded `0.10`) and implements only the 20% referrer share — no admin-80% computation exists.
- **2FA claimed but absent (MAJOR):** §3 Stage 5 and §13 Phase 5 claim "2FA via Telegram"; no TOTP/OTP exists — the second factor is a typed-CONFIRM step only.
- **Linear ghost references (MINOR, pervasive):** real issues run **WARP-1…WARP-41**; every `WARP-42+` ID in code/blueprint/migrations is a ghost (e.g. WARP-50/51/52/53/54/57/59/61/65/71/72/73 appear in source). `WARP-1296` appears in `state/WORKTODO.md:139`.

---

## 2. Findings per Checkpoint

### Checkpoint A — §1 Identity & Access Tiers

| ID | Severity | Claim (blueprint) | Code Truth | Evidence | Recommended Action |
|---|---|---|---|---|---|
| A1 | — (in sync) | `access_tier` dropped in migration 044 | Confirmed dropped | `migrations/044_drop_access_tier.sql:13` `ALTER TABLE users DROP COLUMN IF EXISTS access_tier` | None |
| A2 | — (in sync) | `users.role` RBAC added | Confirmed `role VARCHAR(20) DEFAULT 'user'` | `migrations/045_add_role_column.sql:13` | None |
| A3 | MINOR | Tier 1–4 → role mapping (4 tiers) | Code has only 2 roles (`admin`/`user`); no 4-tier mapping | `bot/middleware/access_tier.py:30,57-96`; `domain/activation/live_checklist.py:186-201` | Blueprint already labels tiers as "functional intent"; add explicit note that only admin/user roles exist |
| A4 | — (in sync) | `access_tier` residuals removed (WARP-40) | Zero `.py` source refs (only the retained module filename `bot/middleware/access_tier.py` + tests) | `grep -rn access_tier` → migrations/docs/tests only | None |
| A5 | MAJOR | (not mentioned) | `user_tiers` table (FREE/PREMIUM/ADMIN) is an active parallel mechanism alongside `users.role` | `migrations/023_user_tiers.sql:4`; `services/tiers.py:18-92`; `bot/roles.py:25`; `bot/handlers/admin.py:64,134` | Document `user_tiers` in blueprint OR consolidate onto `users.role`; only `ADMIN` rank is load-bearing |
| A6 | — (in sync) | Operator allowlist | Root operator = env `OPERATOR_CHAT_ID`; `/allowlist` promotes to `admin` role | `config.py:46`; `bot/handlers/admin.py:46-49,435-465` | Note: legacy in-memory `services/allowlist.py` is unused for operator gating |

### Checkpoint B — §1b Deliberate Divergences Table

| ID | Severity | Claim (blueprint) | Code Truth | Evidence | Recommended Action |
|---|---|---|---|---|---|
| B1 | — | `access_tier` dropped, role RBAC | Confirmed (see A1/A2) | as A1/A2 | None |
| B2 | MAJOR | `copy_targets` → `copy_trade_tasks` "schema rename" | NOT a rename — both tables coexist with different purposes | `copy_targets` `migrations/001_init.sql:77` (redef `009:56`); `copy_trade_tasks` `migrations/018_copy_trade_tasks.sql:5` | Reword §1b: not a rename. `copy_targets` = thin legacy follow record; `copy_trade_tasks` = full dashboard task (TP/SL/slippage/daily-spend) |
| B3 | MINOR | Audit log at "migration 002" | `audit_log` is migration **033**; migration 002 (`002_safety.sql`) creates `chain_cursor` | `migrations/033_risk_caps_audit_log.sql:10`; `migrations/002_safety.sql:2` | Change §1b reference "migration 002" → "migration 033" |
| B4 | MAJOR | Wallet plane partial / single pool | Per-user HD addresses; ledger implemented; no realized single pool, no hot/cold/warm | see Checkpoint H | Reword §1b: code uses per-user HD addresses + logical sweep, not a realized single pool |
| B5 | — (in sync) | 5m/15m discriminator NOT built; crypto-only gate retained | Confirmed: no timeframe gate; crypto-only eligibility gate present (BTC/ETH/SOL/XRP/DOGE/BNB/HYPE) | `domain/strategy/eligibility.py:23-66`; `domain/strategy/strategies/confluence_scalper.py:111` | None |

### Checkpoint C — §2 System Architecture

| ID | Severity | Claim | Code Truth | Evidence | Recommended Action |
|---|---|---|---|---|---|
| C1 | — (in sync) | Three planes (Identity/Trading/Admin-Ops) | Code organization roughly matches (bot/ + domain/ + api/ops) | `domain/`, `bot/handlers/admin.py`, `api/ops.py` | None (spec-level intent) |
| C2 | — (in sync) | Privilege escalation needs cross-plane auth; no silent bypass | Admin endpoints check role/operator; live path requires role=='admin' | `domain/activation/live_checklist.py:186-201`; `bot/handlers/admin.py:46-93` | None |
| C3 | MAJOR | Wallet plane separation (vault+signer+hot/cold) | Vault exists; no separate signer process; no hot/cold split | see Checkpoint H | Aggregate with B4/H — mark §2 wallet-plane block as partially aspirational |

### Checkpoint D — §3 User Journey (6 Stages)

| ID | Severity | Claim | Code Truth | Evidence | Recommended Action |
|---|---|---|---|---|---|
| D1 | — (in sync) | Onboarding `/start` + wallet flow | Implemented; wallet auto-provisioned (no explicit generate-vs-import UI branch) | `bot/handlers/mvp/onboarding.py:49`; `bot/handlers/start.py:63,88-117` | Note "Import Wallet" path is deferred (matches §7) |
| D2 | — (in sync) | Operator allowlist (Stage 2) | `/allowlist` admin command | `bot/handlers/admin.py:435-465` | None |
| D3 | MINOR | Deposit watcher + ledger credit + sweep to hot pool | Watcher + atomic credit implemented; sweep is logical-only (deferred) | `scheduler.py:121,161-185,508-529` | Mark "sweep to hot pool" as deferred in §3 |
| D4 | — (in sync) | Strategy config menus | Implemented (presets, risk, TP/SL, market filters, capital) | `bot/handlers/mvp/autotrade.py:81,203-256`; `bot/handlers/settings.py` | None |
| D5 | MAJOR | Stage 5 "2FA via Telegram" | **2FA MISSING** — typed-CONFIRM step only; activation-guard + live-gate exist | `bot/handlers/live_gate.py:8-12,40`; 2FA refs are comments only (`bot/handlers/activation.py:131`) | Remove "2FA" claim OR build real 2FA; currently misleading |
| D6 | — (in sync) | Monitoring (Dashboard/Positions/Activity/P&L/Force Close/Emergency) | All implemented | `bot/handlers/mvp/dashboard.py:46`; `positions.py` force_close; `bot/handlers/emergency.py:129-184` | None |

### Checkpoint E — §4 Strategy Engine

| ID | Severity | Claim | Code Truth | Evidence | Recommended Action |
|---|---|---|---|---|---|
| E1 | — (in sync) | `BaseStrategy` with `scan`/`evaluate_exit`/`default_tp_sl` | Matches (note `evaluate_exit(position: dict)`) | `domain/strategy/base.py:30-58` | None |
| E2 | — (in sync) | Registry registers CopyTrade, SignalFollowing, ConfluenceScalper, MomentumReversal | Exactly these 4 registered | `domain/strategy/registry.py:162-167` | None |
| E3 | — (in sync) | Lib strategies + ENABLED_STRATEGIES | 11 lib modules present; `ENABLED_STRATEGIES` exists | `lib/strategies/` (11 files); `services/signal_scan/lib_strategy_runner.py:35` | Blueprint §4 hint points at lib/; actual list is in `lib_strategy_runner.py` — update path hint |
| E4 | MINOR | 8 presets | Code has **11** presets in `PRESET_CONFIG` (8 named + `close_sweep`, `pair_arb`, `ensemble`) | `bot/presets.py:25-170` | Add the 3 extra presets to §4 preset table |
| E5 | NIT | Per-strategy `risk_profile_compatibility` incl. custom | Class attr uses {conservative,balanced,aggressive} (no `custom`); gate enforcement via `STRATEGY_AVAILABILITY` includes custom | `domain/strategy/base.py:21-23`; `domain/risk/constants.py:54-61` | Cosmetic — note the gate (not the class attr) is authoritative |
| E6 | — (in sync) | `value`/`full_auto` gated to balanced/aggressive/custom | `STRATEGY_AVAILABILITY["value"]=[balanced,aggressive,custom]` enforced at gate step 4 | `domain/risk/constants.py:58`; `domain/risk/gate.py:256-262` | None |

### Checkpoint F — §5 Telegram Menu

| ID | Severity | Claim | Code Truth | Evidence | Recommended Action |
|---|---|---|---|---|---|
| F1 | — (in sync) | 5-button persistent ReplyKeyboard bar | Implemented (`is_persistent=True`, 5 buttons) | `bot/keyboards/mvp/_common.py:42-64` | Blueprint cites `keyboards/__init__.py`; actual is `keyboards/mvp/_common.py` — fix path |
| F2 | — (in sync) | State-aware `auto_label`/`portfolio_label` | Implemented (Resume/Auto Mode/Setup Auto; Trades(N)/Portfolio) | `bot/keyboards/mvp/_common.py:49-55` | None |
| F3 | — (in sync) | Dashboard/Portfolio/Auto/Settings/Help handlers | All present | `dashboard.py:46`, `portfolio.py:35`, `autotrade.py:81`, `settings.py:39`, `help.py:16` (all `bot/handlers/mvp/`) | None |
| F4 | — (in sync) | Preset Picker screens 03/04/04b | State machine present (onboarding + auto-config) | `bot/handlers/start.py:163,181`; `bot/handlers/mvp/autotrade.py:203-256`; `bot/keyboards/presets.py:11,30` | None |
| F5 | — (in sync) | 10-item tree menu NOT in code | Confirmed: `bot/ui/tree.py` is a formatting module, not a menu tree; 5-button bar is what ships | `bot/ui/tree.py` (used only for constants) | None |

### Checkpoint G — §6 Risk System

| ID | Severity | Claim | Code Truth | Evidence | Recommended Action |
|---|---|---|---|---|---|
| G1 | — (in sync) | 13 hard-wired constants | All 13 match exactly (Kelly 0.25, pos 0.10, corr 0.40, concurrent 5, daily -2000, MDD 0.08, liq 10k, edge 200bps, stale 14400, dedup 300, impact 0.05, slip 0.03, guard 0.05) | `domain/risk/constants.py:4-26` | None |
| G2 | — (in sync) | `MIN_NET_EDGE_VS_COSTS_BPS` not a separate constant | Confirmed absent; repo blueprint note correct (upload version is wrong) | `domain/risk/constants.py` (no such symbol) | None — see Cross-cut D |
| G3 | — (in sync) | 4 profiles incl. custom; custom floor = balanced | Present; custom values mirror balanced | `domain/risk/constants.py:28-52` | None |
| G4 | — (in sync) | Effective limit = most_restrictive(system, profile, user) | `effective_daily_loss` implements max-of-negatives | `domain/risk/constants.py:64-70` | None (generalized only for daily loss) |
| G5 | MAJOR | 13-step gate with tenant_scope/live_mode/capital_mode/cost steps | Code runs steps 0–14; composition differs (step2=pause, step3=role, step4=strategy-availability, step14=market-impact); no discrete tenant/capital/cost steps | `domain/risk/gate.py:212-389` | Rewrite §6 gate flow to match actual step list; or add the missing discrete steps in code |
| G6 | — (in sync) | Exit priority: force→TP→SL→strategy→hold | Implemented (force/TP/SL confirmed; strategy `evaluate_exit` is the post-check hook) | `domain/execution/exit_watcher.py:5-7,186-211`; `domain/strategy/base.py:42-49` | None |
| G7 | — (in sync) | positions carry applied_tp_pct/applied_sl_pct/exit_reason | All present (TP/SL immutable via trigger) | `migrations/001_init.sql:139`; `migrations/005_position_exit_fields.sql:38-41,106-121` | None |

### Checkpoint H — §7 Wallet Plane

| ID | Severity | Claim | Code Truth | Evidence | Recommended Action |
|---|---|---|---|---|---|
| H1 | MAJOR | Custodial-light single pooled hot wallet | Per-user ledger implemented; funds sit at per-user HD addresses — NOT a realized single pool | `wallet/ledger.py:59-71`; `wallet/vault.py:26-43,69-77` | Reword §7 + §1b: per-user addresses + logical sweep, pooling deferred |
| H2 | — (in sync) | HD-derived deposit address per user | Implemented (BIP44 `m/44'/60'/0'/0/{index}`, atomic index reservation) | `wallet/generator.py:10-19`; `wallet/vault.py:14-23` | None |
| H3 | MINOR | On-chain deposit detection (on-chain reader) | Implemented via HTTP `eth_getLogs` polling, NOT Alchemy WebSocket | `integrations/polygon.py:143-198`; `scheduler.py:587-588`; (`ALCHEMY_POLYGON_WS_URL` used only for health ping `monitoring/health.py:132-142`) | Note mechanism is poll-based; functional. Correct any "WebSocket deposit" claim |
| H4 | — (in sync) | Atomic ledger credit on deposit confirm | Single DB txn wraps deposit INSERT + ledger credit; rolls back on failure | `scheduler.py:161-180,193-199` | None |
| H5 | — (in sync) | Dedup key includes `log_index` | `ON CONFLICT (tx_hash, log_index)`; unique constraint in schema | `scheduler.py:169`; `migrations/004_deposit_log_index.sql:43-44` | None |
| H6 | MINOR | (reorg guard expected) | No reorg/`removed`/confirmation-depth handling; deposits credited on first scan | `scheduler.py:119-211`; `integrations/polygon.py` | Add confirmation-depth/reorg guard before live; document as known gap |
| H7 | MINOR | Sweep to hot pool | Logical-only (`deposits.swept=TRUE`); on-chain move deferred behind `EXECUTION_PATH_VALIDATED` | `scheduler.py:508-529,634` | Mark deferred in §7 |
| H8 | MAJOR | Hot/cold/warm split 20-40/30-40/30-50 | Not implemented; single master wallet only; no `proxy_wallet_pool` | `config.py:138`; `wallet/vault.py:69-77` | Mark §7 hot/cold/warm table as deferred/target-only |

### Checkpoint I — §8 Auto-Trade Engine

| ID | Severity | Claim | Code Truth | Evidence | Recommended Action |
|---|---|---|---|---|---|
| I1 | — (in sync) | Per-user execution loop | Implemented (per-user loop in scan job; TradeEngine stateless per-signal) | `services/signal_scan/signal_scan_job.py:747,787-893` | None |
| I2 | — (in sync) | Scan frequency (metadata 5m, signal 1-5m, position WS, resolution 1m) | Implemented; metadata 300s, signal 180s, resolution **300s** (blueprint says 1m), WS heartbeat 10s | `config.py:171,173,191,225-231`; `scheduler.py:589-632` | Fix §8: resolution monitoring is 300s, not 1m |
| I3 | MINOR | Per-user execution lock | No dedicated lock; APScheduler `max_instances=1,coalesce` + unique-key dedup | `scheduler.py:589-593`; `signal_scan_job.py:13-18,540-563` | Document the lock-free-via-unique-constraint design in §8 |
| I4 | MINOR | Per-market size aggregation | MISSING — candidates execute independently (only open-position skip) | `signal_scan_job.py:550-563`; `domain/risk/gate.py:86` | Mark §8 aggregation as not implemented |
| I5 | MINOR | Stagger/jitter 0-3s | MISSING — users/candidates processed back-to-back | `signal_scan_job.py:787-893` | Mark §8 jitter as not implemented |
| I6 | — (in sync) | Stale signal re-validation before execute | Implemented (30m age gate + 25% drift recheck + 4h hard gate) | `signal_scan_job.py:565-623`; `domain/risk/constants.py:12` | None |
| I7 | MINOR | Backpressure on rate limits | MISSING in scan loop (retry+backoff only on RPC; backpressure only in copy-trade watcher) | `integrations/polygon.py:57-64`; `services/copy_trade/wallet_watcher.py:30,49` | Mark §8 backpressure as not implemented |

### Checkpoint J — §9 Auto-Redeem System

| ID | Severity | Claim | Code Truth | Evidence | Recommended Action |
|---|---|---|---|---|---|
| J1 | MINOR | Instant worker subscribes to resolution events | Poll-driven dispatch (resolution scan → async task), not WS/push subscription | `services/redeem/redeem_router.py:46,156,176-179`; `services/redeem/instant_worker.py:41` | Reword §9: "instant" = same-tick dispatch off resolution poll |
| J2 | — (in sync) | Hourly batch worker (cron) | Implemented (drains `redeem_queue` hourly; one redeem/position per CTF) | `services/redeem/hourly_worker.py:32-74`; `scheduler.py:630` | None |
| J3 | — (in sync) | Gas cap protection | Implemented; threshold `INSTANT_REDEEM_GAS_GWEI_MAX=200` (blueprint text says 100 gwei) | `config.py:198`; `instant_worker.py:79-136` | Fix §9 narrative "100 gwei" → 200 gwei (or align config) |
| J4 | — (in sync) | User mode Instant/Hourly | `user_settings.auto_redeem_mode DEFAULT 'hourly'` | `migrations/001_init.sql:72`; `redeem_router.py:132,156` | None |
| J5 | — (in sync) | Audit log on redeem | Multiple audit writes in settle path | `redeem_router.py:277,334,389` | None |
| J6 | MAJOR | `AUTO_REDEEM_ENABLED` default OFF | Code default **True**; guard checked at 3 entry points | `config.py:164`; `redeem_router.py:67`; `instant_worker.py:49-52`; `hourly_worker.py:42-44` | Confirm intentional for paper; add inline comment + reconcile §12 (see M) |

### Checkpoint K — §10 Fee & Referral

| ID | Severity | Claim | Code Truth | Evidence | Recommended Action |
|---|---|---|---|---|---|
| K1 | — (in sync) | `FEE_COLLECTION_ENABLED=False` at launch | Default False; gate early-returns | `config.py:156`; `services/fee/fee_service.py:41` | None |
| K2 | MAJOR | 1% fee, admin 80% / referrer 20% | Fee is **10%** (seeded `0.10`); only the 20% referrer share exists; no admin-80% computation | `services/fee/fee_service.py:22-27,44-46`; `migrations/022_referral_fee_system.sql`; `services/referral/referral_service.py:116` | Reconcile §10: state actual 10% rate and that admin share is implicit remainder |
| K3 | — (in sync) | No exit fee | Confirmed — `calculate_and_record_fee` not called on close/redeem paths | grep of `domain/execution/`, `services/redeem/` (no callers) | None |
| K4 | MAJOR | `users.referrer_user_id` set at user creation | Column is `referrer_id` and is **never written**; attribution lives in `referral_events` | `migrations/001_init.sql:14`; `bot/handlers/onboarding.py:175,187`; `services/referral/referral_service.py:126-176` | Fix §10/§11: rename to `referrer_id` (dead column) and document `referral_events` as the real attribution store |
| K5 | MINOR | Monthly settlement | MISSING — no fee/referral disbursement cron (earnings computed on-read, gated by `REFERRAL_PAYOUT_ENABLED`) | grep `monthly|settlement|payout` (none in `jobs/`/`scheduler.py`) | Mark §10 monthly settlement as not implemented |
| K6 | MINOR | Pre-trade fee preview UI | MISSING — only post-hoc fee in PnL totals | `bot/handlers/dashboard.py:63-69` | Mark §10 fee-preview UI as not implemented |

### Checkpoint L — §11 Database Schema

| ID | Severity | Claim | Code Truth | Evidence | Recommended Action |
|---|---|---|---|---|---|
| L1 | MAJOR | `users`, `sub_accounts`, `sessions` | `users` EXISTS; `sub_accounts` ABSENT; `sessions` DROPPED in 042 | `migrations/001_init.sql:8`; `migrations/042_drop_legacy_sessions.sql:6` | Remove `sub_accounts`+`sessions` from §11 (JWT stateless now) |
| L2 | MAJOR | `users` tuple lists `access_tier` | Contradicts §1/§1b (column dropped) | `docs/blueprint/crusaderbot.md:626` vs `migrations/044` | Remove `access_tier` from §11 users tuple; add `role` |
| L3 | MAJOR | `deposits`, `withdrawals`, `ledger_entries`, `proxy_wallet_pool` | `deposits` EXISTS; `withdrawals` ABSENT; `ledger_entries`→ table is `ledger`; `proxy_wallet_pool` ABSENT | `migrations/001_init.sql:37,50` | Fix names; mark withdrawals/proxy_wallet_pool absent |
| L4 | MINOR | Audit log at migration 002 | `audit_log` is migration **033** (002 = chain_cursor) | `migrations/033_risk_caps_audit_log.sql:10` | Change migration reference to 033 |
| L5 | MAJOR | `markets`,`orders`,`fills`,`positions`,`risk_decisions`,`idempotency_keys` | All exist EXCEPT `risk_decisions` (table is `risk_log`) | `migrations/001_init.sql:109,126,150,161`; `015:51` | Rename `risk_decisions`→`risk_log` |
| L6 | MAJOR | strategy/config 6 tables incl. `user_trade_settings`,`auto_trade_state` | `user_strategies`,`user_risk_profile`,`strategy_definitions` EXIST; `user_market_filters`,`user_trade_settings`,`auto_trade_state` ABSENT (closest `user_settings`) | `migrations/008_strategy_tables.sql:22,34,51`; `001:62` | Fix names; mark 3 tables absent / map to `user_settings` |
| L7 | MAJOR | copy: `copy_targets`,`copy_trade_events`,`wallet_leaderboard` | First two EXIST; `wallet_leaderboard`→`leaderboard_stats`; `copy_trade_tasks` (018) missing from §11 | `migrations/009:162`; `018:5`; `038_leaderboard_stats.sql:3` | Add `copy_trade_tasks`; rename leaderboard table |
| L8 | — (in sync) | `signal_feeds`,`signal_publications`,`user_signal_subscriptions` | All EXIST | `migrations/010_signal_following.sql:47,71,96` | None |
| L9 | MAJOR | `portfolio_snapshots`,`pnl_daily` | `portfolio_snapshots` EXISTS; `pnl_daily` ABSENT | `migrations/029_webtrader_tables.sql:5` | Mark `pnl_daily` absent (or map to daily PnL summary path) |
| L10 | MAJOR | `fee_records`,`referral_links`,`referral_earnings` | All three ABSENT under those names (actual: `fees` 001, `fee_config` 022, `referral_codes` 001, `referral_events` 022); no `referral_earnings` | `migrations/001_init.sql:169,180`; `022_referral_fee_system.sql:26,54` | Rewrite §10/§11 fee+referral table names to match schema |
| L11 | — (in sync) | `system_alerts`,`job_runs`,`kill_switch_history` | All EXIST | `migrations/029:19`; `007_ops.sql:79,68` | None |
| L12 | MINOR | "~34 tables" | ~43 tables at HEAD. Tables NOT in §11: `wallets`,`user_settings`,`chain_cursor`,`live_redemptions`,`redeem_queue`,`system_settings`,`system_flags`,`execution_queue`,`copy_trade_tasks`,`copy_trade_idempotency`,`copy_trade_daily_spend`,`mode_change_events`,`referral_events`,`fee_config`,`user_tiers`,`leaderboard_stats`,`hd_index_counter`,`audit.log` | `migrations/046_enable_rls_anon_lockout.sql:10` ("42 public tables") | Update count to ~43; enumerate the additional tables |

### Checkpoint M — §12 Activation Guards

| Guard | BP default | Code value | Defined? | Checked where | Severity | Evidence |
|---|---|---|---|---|---|---|
| `EXECUTION_PATH_VALIDATED` | OFF | False | yes | sweep/live paths | — | `config.py:149` |
| `CAPITAL_MODE_CONFIRMED` | OFF | False | yes | live gate | — | `config.py:150` |
| `ENABLE_LIVE_TRADING` | OFF | False | yes | execution/live guards | — | `config.py:148` |
| `RISK_CONTROLS_VALIDATED` | OFF | False | yes | readiness | — | `config.py:155` |
| `SECURITY_HARDENING_VALIDATED` | OFF | **not defined** | **no** | n/a | MAJOR | absent from `config.py` |
| `FEE_COLLECTION_ENABLED` | OFF | False | yes | `fee_service.py:41` | — | `config.py:156` |
| `REFERRAL_PAYOUT_ENABLED` | OFF | False | yes | referral earnings | — | `config.py:163` |
| `AUTO_REDEEM_ENABLED` | OFF | **True** | yes | redeem paths | MAJOR | `config.py:164` |

- M-summary: 6 of 8 guards match (defined + default OFF + checked). `SECURITY_HARDENING_VALIDATED` is referenced in §12 but absent from `config.py` (MAJOR — claimed guard cannot gate anything). `AUTO_REDEEM_ENABLED=True` contradicts the §12 "default OFF" rule (MAJOR — likely intentional for paper redeem; recommend documenting).

### Checkpoint N — §13 Roadmap

| ID | Severity | Claim | Code Truth | Evidence | Recommended Action |
|---|---|---|---|---|---|
| N1 | MAJOR | Phase 0–11 roadmap; ROADMAP.md to reflect it | `state/ROADMAP.md` uses "Fast Track Week 1–3 / Tracks A–J" structure, not Phase 0–11 | `state/ROADMAP.md:1-50` | Reconcile §13 with actual ROADMAP.md structure (or update ROADMAP.md) |
| N2 | MINOR | Max `.9` sub-phase normalization | ROADMAP uses Week/Track labels (no `.x` phases) — rule N/A as written | `state/ROADMAP.md` | Note rule does not apply to current Week/Track scheme |
| N3 | MINOR | PR #840 closed legacy paper-beta | Not verifiable from clone (`git log --all` shallow); ROADMAP cites PRs #942–#988 (so #840 is plausibly historical) | `state/ROADMAP.md` PR refs | CMD to confirm PR #840 on GitHub |

---

### Cross-cut A — Linear Ghost References

Real issues in `W.A.R.P ENGINE` (Linear MCP): **WARP-1 … WARP-41** exist. Every `WARP-42+` is a ghost. Load-bearing references (code/blueprint/migrations) below; report-only refs summarized in Appendix B.

| Linear ID | Status | Referenced In | Suggested Title | Recommendation |
|---|---|---|---|---|
| WARP-50 | Ghost | `migrations/045_add_role_column.sql:1` | "Add users.role RBAC column" | CREATE retro-issue or REMOVE comment ref |
| WARP-51 | Ghost | `migrations/024:75`, `migrations/031:4`, `migrations/044:3,10`, blueprint §1b:65 | "Drop access_tier, role RBAC migration" | CREATE retro-issue or REMOVE refs |
| WARP-52 | Ghost | `config.py:189` | "Portfolio snapshots NOTIFY heartbeat" | CREATE retro-issue or REMOVE comment |
| WARP-53 | Ghost | `monitoring/alerts.py:285` | "Reliability hardening / alerts" | CREATE retro-issue or REMOVE comment |
| WARP-54 | Ghost | `bot/handlers/admin.py:268` | "Closed-beta hardening / admin" | CREATE retro-issue or REMOVE comment |
| WARP-57/58/59 | Ghost | `bot/dispatcher.py` (multiple), `bot/handlers/mvp/copy_wallet.py:39`, blueprint §1b:66 | "Telegram UX MVP / copy-trade schema + e2e" | CREATE retro-issues or REMOVE refs |
| WARP-61 | Ghost | blueprint §1b:69 | "Confluence Scalper crypto-only gate post-review" | CREATE retro-issue or REMOVE ref |
| WARP-65(/66/67/68) | Ghost | blueprint §5:241 (`WARP-65/66/67/68`) | "Menu redesign — 5-button bottom bar" | CREATE retro-issue(s) or REMOVE ref |
| WARP-71 | Ghost | `bot/messages_mvp.py:7` | "MVP messages" | CREATE retro-issue or REMOVE comment |
| WARP-72 | Ghost | `bot/handlers/mvp/autotrade.py:164,178` | "Auto-trade MVP handler" | CREATE retro-issue or REMOVE comment |
| WARP-73 | Ghost | `bot/ui/tree.py:1` | "UI tree formatting constants" | CREATE retro-issue or REMOVE comment |
| WARP-1296 | Ghost (anomalous 4-digit) | `state/WORKTODO.md:139` | "RLS enable 42 tables anon lockout" | Correct ID (likely WARP-60-range) or REMOVE |

### Cross-cut B — Migration Number Cross-Check

| Blueprint Claim | Actual File | Status |
|---|---|---|
| audit_log at migration 002 (§1b:67, §11:633) | `033_risk_caps_audit_log.sql` | MINOR drift |
| migration 002 = (implied audit/safety) | `002_safety.sql` creates `chain_cursor` + `orders.error_msg` | confirms 002 ≠ audit |
| `access_tier` dropped migration 044 (§1b:65) | `044_drop_access_tier.sql` | CORRECT |
| `users.role` added (implied) | `045_add_role_column.sql` | CORRECT (referenced as WARP-50 ghost) |
| copy_targets→copy_trade_tasks "rename at 009+" (§1b:66) | `001` creates copy_targets; `009` creates copy_trade_events; `018` creates copy_trade_tasks | MAJOR framing drift (coexist, not rename) |

### Cross-cut C — Blueprint Internal Consistency

| Inconsistency | Sections | Severity | Recommendation |
|---|---|---|---|
| `access_tier` claimed dropped but still in §11 `users` tuple | §1, §1b, §11:626 | MAJOR | Remove `access_tier` from §11 tuple; add `role VARCHAR` |
| Audit log "separate DB, INSERT-only" (§11/§5) vs "single-DB gap, deferred" (§1b) | §1b:67, §11:631-657, §5 | MINOR | Align §11 audit section with §1b reality (single-DB, append-only not yet enforced) |
| §1b says `copy_trade_tasks` is canonical but §11 lists `copy_targets`/`copy_trade_events` and omits `copy_trade_tasks` | §1b:66, §11:689-694 | MINOR | Add `copy_trade_tasks` to §11; clarify roles of both |
| §3/§13 claim "2FA via Telegram" but feature absent | §3:161, §13:811 | MAJOR | Remove 2FA claim or build it |
| "~34 tables" vs actual ~43 | §11:723 | MINOR | Update count |

### Cross-cut D — Two Blueprint Versions

The repo `docs/blueprint/crusaderbot.md` (15:30 stamp, commit `1afba00`) is the canonical v3.2 and is materially more code-accurate than the uploaded 14:30 version (old 7-row strategy table, full 10-item tree menu in §5, and a spurious `MIN_NET_EDGE_VS_COSTS_BPS` constant in §6). **D1:** repo version confirmed canonical. **D2:** the 14:30 upload is superseded/stale. **D3:** the 14:30 version is NOT committed anywhere in the repo as a blueprint (grep for the `14:30` stamp hits only report/state narrative, not a blueprint copy) — no repo deletion required; discard the external upload copy.

---

## 3. Sync Action List

### 3.1 Blueprint changes recommended

1. `docs/blueprint/crusaderbot.md:626` — remove `access_tier` from `users` tuple; add `role VARCHAR(20)`.
2. `docs/blueprint/crusaderbot.md:67` (§1b) and `:633` (§11) — change audit-log "migration 002" → "migration 033".
3. `docs/blueprint/crusaderbot.md:66` (§1b) — reword copy_targets→copy_trade_tasks: not a rename; both coexist (`copy_targets` legacy follow record vs `copy_trade_tasks` dashboard task).
4. §11 (`:622-723`) — full table-name reconciliation: `ledger_entries`→`ledger`, `risk_decisions`→`risk_log`, `user_trade_settings`→`user_settings`, `wallet_leaderboard`→`leaderboard_stats`, `fee_records`→`fees`/`fee_config`, `referral_links`→`referral_codes`, `referral_earnings`→`referral_events`; mark `sub_accounts`, `sessions`, `withdrawals`, `proxy_wallet_pool`, `user_market_filters`, `auto_trade_state`, `pnl_daily` as absent/deferred; add `copy_trade_tasks`, `user_tiers`, `chain_cursor`, `execution_queue`, `redeem_queue`, etc.; change "~34" → "~43".
5. §11 audit section (`:631-657`) — align with §1b: single-DB, append-only not yet enforced.
6. §3:161 + §13:811 — remove "2FA via Telegram" (not implemented) or reclassify as deferred.
7. §6 risk-gate flow (`:350-384`) — rewrite to match actual `gate.py` step composition (0–14).
8. §8:494 — resolution monitoring is 300s, not 1m; mark per-market aggregation / jitter / backpressure as not implemented.
9. §9:556 — gas cap is 200 gwei (config), not 100; "instant" = poll-driven dispatch.
10. §10 — fee rate is 10% not 1%; admin-80% split not implemented; referral attribution via `referral_events`, not `users.referrer_user_id`; monthly settlement + pre-trade fee preview not implemented.
11. §4 preset table — add `close_sweep`, `pair_arb`, `ensemble` (11 presets, not 8).
12. §12 — add `user_tiers` parallel mechanism note; reconcile `AUTO_REDEEM_ENABLED` (True) and `SECURITY_HARDENING_VALIDATED` (undefined).
13. §13 — reconcile Phase 0–11 with the actual Fast Track Week/Track ROADMAP structure.

### 3.2 Code changes recommended

These are recommendations only — SENTINEL does not patch. CMD/FORGE to route.

1. `config.py:164` — confirm `AUTO_REDEEM_ENABLED = True` is intentional for paper mode; add inline comment, or flip to False to match §12.
2. `config.py` — add `SECURITY_HARDENING_VALIDATED: bool = False` so the §12 guard exists and can gate.
3. `scheduler.py` deposit path — add confirmation-depth / reorg guard before any live capital movement (H6).
4. (Optional, pre-live) `services/fee/fee_service.py` — implement explicit admin-share recording if the 80/20 split is a real launch requirement (K2).

### 3.3 Linear issue recommendations

- CREATE retro-issues (or REMOVE source comments) for ghost IDs referenced in **source/migrations**: WARP-50, WARP-51, WARP-52, WARP-53, WARP-54, WARP-57, WARP-59, WARP-71, WARP-72, WARP-73.
- CREATE retro-issues (or REMOVE refs) for ghost IDs in the **blueprint**: WARP-51, WARP-57/58/59, WARP-61, WARP-65(/66/67/68).
- FIX anomalous `WARP-1296` in `state/WORKTODO.md:139` (no such issue; likely a typo).
- Decision belongs to WARP🔹CMD: bulk-create retro-issues to legitimize references, or strip ghost IDs from comments.

---

## 4. Out-of-Scope Observations

- `config.py:159-162` defines a second risk-cap layer (`MAX_SINGLE_POSITION_PCT`, `MAX_TOTAL_EXPOSURE_PCT=0.80`, `MAX_DAILY_LOSS_USD=-50.0`, `MAX_OPEN_POSITIONS=20`) enforced by gate step 0 (`validate_risk_caps`) — values differ from the §6 hard constants; not audited further.
- Two audit tables exist (`audit.log` schema table from 001 + `audit_log` from 033) — potential confusion; not investigated.
- Legacy `docs/crusader_multi_user_architecture_blueprint.md` (v1) and `docs/crusaderbot_blueprint.html` exist — out of scope per task.
- `services/allowlist.py` (in-memory Tier-2 store) appears unused for operator gating — possible dead code; not investigated.

---

## 5. Methodology Notes

- HEAD SHA captured at audit start: `1afba00eb55dfa0c20e12e0dc26976b1c92df921` (matches blueprint authority commit). No mid-audit change.
- Linear queried via MCP `W.A.R.P ENGINE` team (`3f071118-b961-40d0-924b-be81b7f30406`): issues WARP-1…WARP-41 exist; WARP-41 = this audit.
- Code is authority; blueprint demoted to target intent per task rules.
- No code, migration, config, blueprint, or state file modified. No PR/Linear issue created or changed. No tests run. No CI triggered.
- Sources NOT consulted: live DB (out of scope — migrations used as schema evidence), Sentry, legacy v1 blueprint, legacy HTML blueprint.

---

## 6. Appendix

### A. Grep / query command log

```bash
git rev-parse HEAD                      # 1afba00...
grep -rnoE "WARP-[0-9]+" . ../../../docs/
grep -rn "access_tier" projects/polymarket/crusaderbot/
grep -rn "ENABLED_STRATEGIES" --include=*.py .
grep -nE "GateResult|reason=" domain/risk/gate.py
ls migrations/                          # see C
# Linear MCP: list_teams; list_issues(team=W.A.R.P ENGINE, limit=250)
```

### B. WARP-XX references found across repo (raw summary)

- **Exist in Linear:** WARP-1 … WARP-41.
- **Ghost in source code/migrations:** WARP-50 (045), WARP-51 (024,031,044), WARP-52 (config.py:189), WARP-53 (monitoring/alerts.py:285), WARP-54 (admin.py:268), WARP-57 (dispatcher.py), WARP-59 (copy_wallet.py:39), WARP-71 (messages_mvp.py:7), WARP-72 (autotrade.py:164,178), WARP-73 (ui/tree.py:1). Also WARP-26 (domain/signal/base.py:3).
- **Ghost in blueprint:** WARP-51, WARP-57, WARP-58, WARP-59, WARP-61, WARP-65 (and bare 66/67/68).
- **Ghost in project docs:** WARP-41/WARP-42 (`docs/ux-blueprint-v7.md:3`), WARP-40 (`:93`).
- **Ghost in reports/ (report-only, lower priority):** WARP-42…WARP-68 appear across `reports/forge/*` (e.g. warp51/53/54/56/57/58/59 report files), WARP-67 (`fix-bot-ui-tree-constants.md:12`).
- **Anomalous:** WARP-1296 (`state/WORKTODO.md:139`).

### C. Migration index (`ls migrations/` snapshot)

```
001_init.sql 002_safety.sql 003_live_safety.sql 004_deposit_log_index.sql
005_position_exit_fields.sql 006_redeem_queue.sql 007_ops.sql 008_strategy_tables.sql
009_copy_trade.sql 010_signal_following.sql 011_execution_queue.sql
012_backfill_signal_following_strategy.sql 013_copy_trade_events_nullable_fk.sql
014_add_is_demo_flag.sql 015_order_lifecycle.sql 016_preset_system.sql 017_user_locked.sql
018_copy_trade_tasks.sql 019_onboarding_flag.sql 020_copy_trade_execution.sql
021_mode_change_events.sql 022_referral_fee_system.sql 022b_fix_partial_022.sql
022c_add_trade_id_to_fees.sql 023_user_tiers.sql 024_signal_scan_engine_seed.sql
025_heisenberg_live_feed.sql 026_add_strategy_type_to_orders.sql 027_notifications_on.sql
028_add_preset_activated_at.sql 029_webtrader_tables.sql 030_job_runs_metadata.sql
031_signal_scanner_user_enrollment.sql 032_copy_trade_events.sql 033_risk_caps_audit_log.sql
034_positions_denorm_columns.sql 035_copy_trade_extend.sql 036_ui_responsive_polish.sql
037_safety_phase2.sql 038_leaderboard_stats.sql 039_leaderboard_clear_fake.sql
040_r5_strategy_config.sql 041_positions_strategy_type.sql 042_drop_legacy_sessions.sql
043_strategy_params.sql 044_drop_access_tier.sql 045_add_role_column.sql
046_enable_rls_anon_lockout.sql
```

---

**End of audit.**

