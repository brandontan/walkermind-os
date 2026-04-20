# Phase 8.3 — Public Paper Beta Spine Runtime Contract

## Entrypoints
- API: `projects/polymarket/polyquantbot/server/main.py`
- Telegram Bot: `projects/polymarket/polyquantbot/client/telegram/bot.py`
- Worker: `projects/polymarket/polyquantbot/scripts/run_worker.py`
- Launch helpers:
  - `projects/polymarket/polyquantbot/scripts/run_api.py`
  - `projects/polymarket/polyquantbot/scripts/run_bot.py`

## FastAPI control plane
- `GET /health`
- `GET /ready`
- `GET /beta/status`
- `GET /beta/admin`
- `POST /beta/mode`
- `POST /beta/autotrade`
- `POST /beta/kill`
- `GET /beta/positions`
- `GET /beta/pnl`
- `GET /beta/risk`
- `GET /beta/markets`
- `GET /beta/market360/{condition_id}`
- `GET /beta/social?topic=...`

### Readiness truth (Phase 8.6 confidence pass)
`GET /ready` reports readiness dimensions for this lane:
- Readiness scope contract (`contract_version`, `runtime_assertion`, `worker_state_visibility`, `external_dependencies_probed=false`)
- API boot completion (`api_boot_complete`)
- Worker runtime status (`startup_complete`, `active`, `shutdown_complete`, `iterations_total`, `last_iteration_visible`, `last_error`)
- Worker prerequisites (`paper_mode_enforced`, `autotrade_enabled`, `kill_switch_enabled`, `execution_ready_for_paper_entries`)
- Falcon config truth (`enabled`, `api_key_configured`, `enabled_without_api_key`, `config_valid_for_enabled_mode`, `candidate_source_contract`)
- Control-plane execution boundary (`paper_only_execution_boundary=true`, `live_mode_execution_allowed=false`)

Readiness intentionally does **not** overclaim external dependency health that is not actively probed.
`/ready` should be interpreted as local runtime and control-plane truth, not as Falcon/Telegram upstream health.

## Falcon backend-managed contract
Falcon config is backend-managed only using environment variables:
- `FALCON_API_KEY` (required only when `FALCON_ENABLED=true`)
- `FALCON_BASE_URL`
- `FALCON_TIMEOUT`
- `FALCON_ENABLED`

No user-managed key flow and no `/setkey` command is provided.

### Runtime truth note
This lane is **NARROW INTEGRATION**. Falcon market/candidate/social data currently includes bounded placeholder/sample behavior in `FalconGateway` and is not yet a full production retrieval surface.

## Telegram command shell (public beta)
- `/start`
- `/mode [paper|live]`
- `/autotrade [on|off]`
- `/positions`
- `/pnl`
- `/risk`
- `/status`
- `/markets [query]`
- `/market360 [condition_id]`
- `/social [topic]`
- `/kill`

Manual trade-entry commands are intentionally excluded.
`/mode live` is accepted as control-plane state only in this phase; execution remains paper-only.

### Operator-facing command semantics (completion pass)
- `/status` reports operator guard truth (`entry_allowed`, blocked reasons, last risk reason, mode/autotrade/kill state, and paper-only boundary reminder).
- `/positions`, `/pnl`, and `/risk` are explicitly informational control/read surfaces and do not grant execution authority.
- `/start` and unresolved-user onboarding replies explicitly state this is a public **paper** beta control surface with no manual trade-entry path.

## Paper worker flow
`market_sync -> signal_runner -> risk_monitor -> position_monitor -> price_updater`

Execution mode defaults to `paper`. New entries are blocked when:
- `autotrade_enabled=false`
- `kill_switch=true`
- `mode != paper` (`mode_live_paper_execution_disabled`)
- risk gate rejects EV/edge/liquidity/drawdown/exposure/idempotency checks

Monitoring/update stages still run even when entry creation is blocked.
Worker iteration logs include candidate count, accepted/rejected counts, skip reasons, rejection reason counts, and current position count.

## Fly deploy truth
Fly runtime is paper-mode by default. To activate Falcon-backed candidate generation, deploy must provide secret-backed Falcon configuration (`FALCON_ENABLED=true` + `FALCON_API_KEY` and optional base URL override).


## Operator expectations (public paper beta)
- Telegram is a **control shell**, not a manual trade terminal.
- `/mode live` updates control-plane state only; execution stays paper-only in this phase.
- `/autotrade on` is rejected when mode is `live` to preserve paper-only boundary truth.
- `/kill` always forces autotrade OFF and sets a hard paper-beta execution block.
- `/beta/status` includes `execution_guard` with concrete blocked reasons, `reason_count`, and `operator_summary` for operator visibility.
- `/beta/status` includes `readiness_interpretation` (`control_surface`, `execution_authority`, `live_trading_ready=false`) to prevent overclaiming readiness.
- `/beta/status` and `/beta/admin` include machine-readable `exit_criteria` and `managed_beta_state` payloads so operators/admins can verify managed-beta controllability without implying live authority.
- Unknown Telegram commands fall back to a concise supported-command hint and restate that manual trade-entry commands are not available in this beta.

## Paper-beta exit criteria (Phase 8.8 hardening)
“Paper beta complete” for this managed slice means the control plane can explicitly show:
- readiness contract surfaces are present (`/health`, `/ready`, `/beta/status`, `/beta/admin`)
- paper-only execution boundary is enforced
- autotrade guard behavior is active and truthful
- kill-switch behavior is active and truthful
- onboarding/session control path availability is visible as control-plane prerequisite truth
- required config validity is visible for enabled/disabled Falcon modes
- known limitations are explicitly disclosed and live-readiness is still `false`

These checks are exposed under `exit_criteria.checks` with per-check `pass` and `detail` values.

## Operator/admin verification checklist
- Verify `/beta/status` returns `paper_only_execution_boundary=true`
- Verify `/beta/status.execution_guard` includes blocked reasons and reason count
- Verify `/beta/status.managed_beta_state` reports whether the beta is currently `managed` or `needs_attention`
- Verify `/beta/admin.admin_summary.live_execution_privileges_enabled=false`
- Verify `/beta/status.readiness_interpretation.live_trading_ready=false`
- Verify `/beta/admin.exit_criteria.checks.required_config_present.pass` matches Falcon env reality

## Explicit non-goals and live-readiness block
- No live trading rollout or privileged live execution controls
- No admin trade-entry commands
- No user-managed Falcon keys
- No dashboard expansion
- No broad auth redesign, wallet lifecycle expansion, or strategy/ML expansion

This remains a bounded public **paper** beta control/read lane. Even with managed-beta exit criteria present, it is not a live-ready trading product.

## Known limitations
- Falcon data surfaces remain narrow/placeholder-bounded outside `market_360`; signal quality is not a production claim.
- This lane does not include live execution authority, user-managed Falcon keys, dashboard expansion, or manual trade-entry commands.
