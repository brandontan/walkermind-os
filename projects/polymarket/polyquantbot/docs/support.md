# CrusaderBot — Support & Known Issues

Current known issues and deferred items as of Priority 8 build complete.

---

## Known Issues

### Worker / Execution

**PaperBetaWorker price_updater path not reachable in live mode**
`PaperBetaWorker.run_once()` skips `price_updater()` entirely in live mode — `market_data_provider` injection path in `price_updater()` is never reached from the worker loop. Deferred fix; non-critical per SENTINEL F-1.

**ClobExecutionAdapter mode label not enforced**
`ClobExecutionAdapter` mode=`mocked` label is not enforced against client type. Pre-existing risk (SENTINEL F-1, PR #813). Deferred to P9 hardening.

### Telegram / Operator

**handle_wallet_lifecycle_status() not routed**
Function exists and is tested but Telegram command routing is deferred.

### Database / Persistence

**No migration runner configured**
`001_settlement_tables.sql` and `002_capital_mode_confirmations.sql` must be applied manually or via operator tooling. Auto-create in `_apply_schema()` remains the runtime path.

**get_failed_batches() always returns []**
Batch results are not persisted in the current settlement persistence layer. The `/failed_batches` Telegram reply acknowledges this explicitly.

**OperatorConsole.apply_admin_intervention() does not persist to DB**
Audit log is emitted via structlog (`operator_admin_intervention_audit`) on every intervention. DB persistence deferred to P9 storage lane.

### Multi-User / Portfolio

**Wallet lifecycle live PostgreSQL validation deferred**
Pre-public sweep required before declaring live PostgreSQL wallet lifecycle validated.

**Portfolio routes hardcode tenant_id and user_id**
`tenant_id=system` and `user_id=paper_user` are hardcoded. Per-user route binding deferred to full multi-user rollout.

**Portfolio unrealized PnL uses paper position price**
`current_price` in `paper_positions` is used for unrealized PnL. Live mark-to-market deferred to market data integration lane.

**WalletCandidate financial fields default to 0.0**
`balance_usd`, `exposure_pct`, `drawdown_pct` default to 0.0 — risk gate thresholds will not trigger in orchestration routing until market data integration is complete.

### Capital Mode

**Capital-mode pending-token store is in-process**
`_PENDING_CAPITAL_CONFIRMS` in `server/api/public_beta_routes.py` is an in-process store. Multi-replica deployments require Redis-backed swap before horizontal scale. Acceptable for current single-machine Fly runtime.

### Test Infrastructure

**P8C asyncio.get_event_loop() pattern breaks test isolation**
`asyncio.get_event_loop().run_until_complete` deprecated pattern breaks test isolation when run after P8E. Pre-existing fragility (SENTINEL F-2). Deferred.

---

## Deferred Items

These are intentionally deferred and tracked in `state/WORKTODO.md`:

- Onboarding / account-link full UX (deferred post-public)
- Persistent session test coverage (deferred)
- Per-wallet exposure calculation via live market data (deferred to market data integration lane)
- Docs sync for older phase references (deferred to P9 Lane 1)
- Wallet lifecycle live PostgreSQL validation (deferred to pre-public sweep)

---

## How to Report an Issue

This is a closed-beta system. Issues are tracked internally via GitHub Issues in the `bayuewalker/walkermind-os` repo. If you have operator access, post to the Telegram operator channel or open a GitHub issue with:

1. Steps to reproduce
2. Expected vs actual behavior
3. Relevant log output (remove any secrets/tokens)
