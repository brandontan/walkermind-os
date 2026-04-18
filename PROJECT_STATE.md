Last Updated : 2026-04-19 05:03
Status       : CrusaderBot Fly.io deploy-readiness runtime split is in progress on branch `refactor/infra-crusaderbot-fly-readiness-20260419`; new FastAPI, Telegram, and worker runtime surfaces are added under `projects/polymarket/polyquantbot/` and Fly/Docker now target the API surface instead of the monolithic root `main.py`.

[COMPLETED]
- Phase 6.6.8 public safety hardening merged via PR #565.
- Phase 6.6.9 minimal execution hook merged via PR #566.
- Phase 7.0 deterministic public activation cycle orchestration foundation merged and preserved.
- Phase 7.1 public activation trigger surface merged with one synchronous CLI invocation path mapping run_public_activation_cycle outcomes to explicit completed/stopped_hold/stopped_blocked trigger results.
- Phase 7.2 lightweight automation scheduler merged with deterministic triggered/skipped/blocked result categories and invalid_contract blocked path for negative quota.
- Phase 7.3 runtime auto-run loop FOUNDATION finalized as merged-main truth with preserved bounded synchronous loop behavior and preserved result categories (completed/stopped_hold/stopped_blocked/exhausted) over the Phase 7.2 scheduler boundary.
- Phase 7.4 observability / visibility foundation merged to main; deterministic visibility records (visible/partial/blocked) over Phase 6.4.1 monitoring evaluations, Phase 7.2 scheduler decisions, and Phase 7.3 loop outcomes in monitoring/observability_foundation.py with 45 passing tests.
- Phase 7.5 operator control / manual override merged to main via PR #575 with deterministic OperatorControlDecision (allow/hold/force_block/force_run) injected before Phase 7.2 scheduler decision and Phase 7.3 loop continuation through OperatorSchedulerGate + OperatorLoopGate.
- Phase 7.6 state persistence / execution memory FOUNDATION completed as preserved baseline with deterministic local-file load/store/clear boundary in core/execution_memory_foundation.py for explicit last-run context and invalid_contract blocked behavior.
- Phase 7.7 recovery / resume FOUNDATION safety semantics fix merged via PR #577 with deterministic force_block -> blocked, hold -> restart_fresh, and closed terminal loop outcomes (completed/stopped_hold/exhausted) -> restart_fresh over Phase 7.6 execution memory only; excludes distributed recovery, daemon orchestration, replay engine, database rollout, Redis, async workers, and crash supervision.

[IN PROGRESS]
- CrusaderBot Fly.io deploy-readiness refactor is in progress on branch `refactor/infra-crusaderbot-fly-readiness-20260419` with new `server/main.py`, `client/telegram/bot.py`, and `scripts/run_api.py` runtime surfaces plus Docker/Fly contract updates.

[NOT STARTED]
- Full wallet lifecycle implementation including secure rotation, vault integration, and production orchestration.
- Portfolio management logic and multi-wallet orchestration.
- Automation, retry, and batching for settlement and wallet operations.

[NEXT PRIORITY]
- SENTINEL to validate the CrusaderBot Fly.io deploy path, FastAPI lifecycle contract, startup validation behavior, and the documented legacy boundary before merge.

[KNOWN ISSUES]
- Phase 5.2 only supports single-order transport and intentionally excludes retry, batching, and async workers.
- Phase 6.4 narrow monitoring remains intentionally scoped and not yet the active implementation lane.
- [DEFERRED] Pytest config emits Unknown config option: asyncio_mode warning -- carried forward as non-runtime higiene backlog.
