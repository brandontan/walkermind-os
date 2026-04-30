# Phase 8.3 — Public Paper Beta Spine

**Date:** 2026-04-20 00:15
**Branch:** refactor/public-paper-beta-spine-20260419

## 1. What was built
Built a MAJOR-scope public paper beta runtime spine with independent API, Telegram, and worker entrypoints. Added backend-managed Falcon contract, Telegram control-shell command coverage, paper-only worker flow, and risk-gated execution boundaries.

## 2. Current system architecture (relevant slice)
`Telegram command` -> `client/telegram/dispatcher.py` -> `server/api/public_beta_routes.py` -> `server/core/public_beta_state.py`

`Worker` -> `server/workers/paper_beta_worker.py` -> `server/integrations/falcon_gateway.py` -> `server/risk/paper_risk_gate.py` -> `server/execution/paper_execution.py` -> `server/portfolio/paper_portfolio.py`

FastAPI control plane remains bootstrapped via `server/main.py` with `/health` + `/ready` and `/beta/*` control endpoints.

## 3. Files created / modified (full repo-root paths)
### Created
- projects/polymarket/polyquantbot/configs/falcon.py
- projects/polymarket/polyquantbot/server/core/public_beta_state.py
- projects/polymarket/polyquantbot/server/integrations/falcon_gateway.py
- projects/polymarket/polyquantbot/server/risk/paper_risk_gate.py
- projects/polymarket/polyquantbot/server/execution/paper_execution.py
- projects/polymarket/polyquantbot/server/portfolio/paper_portfolio.py
- projects/polymarket/polyquantbot/server/workers/paper_beta_worker.py
- projects/polymarket/polyquantbot/server/api/public_beta_routes.py
- projects/polymarket/polyquantbot/docs/public_paper_beta_spine.md
- projects/polymarket/polyquantbot/tests/test_phase8_3_public_paper_beta_spine_20260419.py

### Modified in this fix pass
- projects/polymarket/polyquantbot/server/workers/paper_beta_worker.py
- projects/polymarket/polyquantbot/server/api/public_beta_routes.py
- projects/polymarket/polyquantbot/client/telegram/dispatcher.py
- projects/polymarket/polyquantbot/client/telegram/bot.py
- projects/polymarket/polyquantbot/client/telegram/runtime.py
- projects/polymarket/polyquantbot/docs/public_paper_beta_spine.md
- projects/polymarket/polyquantbot/fly.toml
- PROJECT_STATE.md
- ROADMAP.md
- projects/polymarket/polyquantbot/reports/forge/phase8-3_04_public-paper-beta-spine.md

## 4. What is working
- Worker now enforces autotrade gate truthfully: `autotrade_enabled=false` blocks new entries and logs skip reason.
- Kill switch blocks new entries and logs skip reason.
- `/positions`, `/pnl`, `/risk`, `/status` now map to truthful endpoint semantics (`/beta/positions`, `/beta/pnl`, `/beta/risk`, `/beta/status`).
- `/connect_wallet` acknowledgement-only stub was removed from public beta command shell and docs.
- Fly deploy contract now states paper defaults while requiring secret-backed Falcon settings for live candidate generation.

## 5. Known issues
- Falcon integration remains narrow: `FalconGateway` still contains bounded placeholder/sample market/social/candidate behavior and is not full production retrieval authority.
- Telegram replies remain compact text payloads suitable for beta operator control; advanced UX formatting is deferred.

## 6. What is next
- SENTINEL MAJOR validation is required before merge (PR #620 fix pass).
- COMMANDER review after SENTINEL verdict.

## 7. Fix pass (PR #620 contract corrections)
- Added explicit autotrade skip boundary in worker execution loop.
- Removed fake `/connect_wallet` command from runtime command shell.
- Added dedicated `/beta/pnl` and `/beta/risk` endpoints and remapped dispatcher commands.
- Updated Fly/env/docs wording to avoid overclaiming operational Falcon behavior without secrets.
- Added focused tests for autotrade/kill switch execution gating and Telegram command-to-endpoint mapping semantics.

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : autotrade/kill gate enforcement, truthful command routing, Fly runtime contract wording alignment, and honest placeholder disclosure
Not in Scope      : public live rollout, multi-exchange, heavy ML expansion, large dashboard, user-managed Falcon key onboarding
Suggested Next    : SENTINEL review required before merge
