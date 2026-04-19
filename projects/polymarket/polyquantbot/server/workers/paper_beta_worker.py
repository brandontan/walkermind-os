"""Public paper beta worker flow: sync -> signal -> risk -> position -> update."""
from __future__ import annotations

import asyncio
from collections import Counter

import structlog

from projects.polymarket.polyquantbot.configs.falcon import FalconSettings
from projects.polymarket.polyquantbot.server.core.public_beta_state import STATE, WorkerIterationSummary
from projects.polymarket.polyquantbot.server.execution.paper_execution import PaperExecutionEngine
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import FalconGateway
from projects.polymarket.polyquantbot.server.portfolio.paper_portfolio import PaperPortfolio
from projects.polymarket.polyquantbot.server.risk.paper_risk_gate import PaperRiskGate

log = structlog.get_logger(__name__)


class PaperBetaWorker:
    def __init__(self, falcon: FalconGateway, risk_gate: PaperRiskGate, engine: PaperExecutionEngine) -> None:
        self._falcon = falcon
        self._risk_gate = risk_gate
        self._engine = engine

    async def run_once(self) -> list[dict[str, object]]:
        await self.market_sync()
        candidates = await self.signal_runner()
        events: list[dict[str, object]] = []
        risk_rejection_reasons: Counter[str] = Counter()
        summary = WorkerIterationSummary(candidate_count=len(candidates))

        for candidate in candidates:
            if STATE.mode != "paper":
                STATE.last_risk_reason = "mode_live_paper_execution_disabled"
                summary.skip_mode_count += 1
                log.info(
                    "paper_beta_worker_execution_skipped",
                    reason="mode_live_paper_execution_disabled",
                    mode=STATE.mode,
                    autotrade_enabled=STATE.autotrade_enabled,
                    kill_switch=STATE.kill_switch,
                    signal_id=candidate.signal_id,
                    execution_boundary="paper_only",
                )
                continue
            if not STATE.autotrade_enabled:
                STATE.last_risk_reason = "autotrade_disabled"
                summary.skip_autotrade_count += 1
                log.info(
                    "paper_beta_worker_execution_skipped",
                    reason="autotrade_disabled",
                    mode=STATE.mode,
                    autotrade_enabled=STATE.autotrade_enabled,
                    kill_switch=STATE.kill_switch,
                    signal_id=candidate.signal_id,
                    execution_boundary="paper_only",
                )
                continue
            if STATE.kill_switch:
                STATE.last_risk_reason = "kill_switch_enabled"
                summary.skip_kill_count += 1
                log.info(
                    "paper_beta_worker_execution_skipped",
                    reason="kill_switch_enabled",
                    mode=STATE.mode,
                    autotrade_enabled=STATE.autotrade_enabled,
                    kill_switch=STATE.kill_switch,
                    signal_id=candidate.signal_id,
                    execution_boundary="paper_only",
                )
                continue
            decision = self._risk_gate.evaluate(candidate, STATE)
            STATE.last_risk_reason = decision.reason
            if not decision.allowed:
                summary.rejected_count += 1
                risk_rejection_reasons[decision.reason] += 1
                log.info(
                    "paper_beta_worker_risk_rejected",
                    signal_id=candidate.signal_id,
                    reason=decision.reason,
                )
                continue
            event = self._engine.execute(candidate, STATE)
            summary.accepted_count += 1
            events.append(event)
            log.info(
                "paper_beta_worker_position_opened",
                signal_id=candidate.signal_id,
                condition_id=event["condition_id"],
                side=event["side"],
                mode=event["mode"],
                size=event["size"],
            )

        await self.position_monitor()
        await self.price_updater()
        summary.current_position_count = len(STATE.positions)
        summary.risk_rejection_reasons = dict(risk_rejection_reasons)
        summary.rejected_count += (
            summary.skip_autotrade_count + summary.skip_kill_count + summary.skip_mode_count
        )
        STATE.worker_runtime.last_iteration = summary
        STATE.worker_runtime.iterations_total += 1
        log.info(
            "paper_beta_worker_iteration_summary",
            candidate_count=summary.candidate_count,
            accepted_count=summary.accepted_count,
            rejected_count=summary.rejected_count,
            skip_autotrade_count=summary.skip_autotrade_count,
            skip_kill_count=summary.skip_kill_count,
            skip_mode_count=summary.skip_mode_count,
            current_position_count=summary.current_position_count,
            risk_rejection_reasons=summary.risk_rejection_reasons,
        )
        return events

    async def market_sync(self) -> None:
        await asyncio.sleep(0)

    async def signal_runner(self):
        return await self._falcon.rank_candidates()

    async def risk_monitor(self) -> str:
        return STATE.last_risk_reason

    async def position_monitor(self) -> int:
        return len(STATE.positions)

    async def price_updater(self) -> None:
        await asyncio.sleep(0)


async def run_worker_loop(iterations: int = 1) -> None:
    falcon = FalconGateway(FalconSettings.from_env())
    worker = PaperBetaWorker(
        falcon=falcon,
        risk_gate=PaperRiskGate(),
        engine=PaperExecutionEngine(PaperPortfolio()),
    )
    STATE.worker_runtime.active = True
    STATE.worker_runtime.startup_complete = True
    STATE.worker_runtime.shutdown_complete = False
    STATE.worker_runtime.last_error = ""
    log.info(
        "paper_beta_worker_started",
        requested_iterations=max(iterations, 1),
        mode=STATE.mode,
        autotrade_enabled=STATE.autotrade_enabled,
        kill_switch=STATE.kill_switch,
        execution_boundary="paper_only",
    )
    try:
        for _ in range(max(iterations, 1)):
            events = await worker.run_once()
            log.info(
                "paper_beta_worker_iteration",
                positions=len(STATE.positions),
                emitted_events=len(events),
                mode=STATE.mode,
                autotrade_enabled=STATE.autotrade_enabled,
                kill_switch=STATE.kill_switch,
                paper_only_execution=True,
            )
            await asyncio.sleep(0)
    except Exception as exc:
        STATE.worker_runtime.last_error = str(exc)
        log.exception("paper_beta_worker_failed", error=str(exc))
        raise
    finally:
        STATE.worker_runtime.active = False
        STATE.worker_runtime.shutdown_complete = True
        log.info(
            "paper_beta_worker_stopped",
            iterations_total=STATE.worker_runtime.iterations_total,
            last_error=STATE.worker_runtime.last_error,
        )
