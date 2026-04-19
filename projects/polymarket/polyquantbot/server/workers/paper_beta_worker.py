"""Public paper beta worker flow: sync -> signal -> risk -> position -> update."""
from __future__ import annotations

import asyncio

import structlog

from projects.polymarket.polyquantbot.configs.falcon import FalconSettings
from projects.polymarket.polyquantbot.server.core.public_beta_state import STATE
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
        for candidate in candidates:
            if not STATE.autotrade_enabled:
                STATE.last_risk_reason = "autotrade_disabled"
                log.info(
                    "paper_beta_worker_execution_skipped",
                    reason="autotrade_disabled",
                    signal_id=candidate.signal_id,
                )
                continue
            if STATE.kill_switch:
                STATE.last_risk_reason = "kill_switch_enabled"
                log.info(
                    "paper_beta_worker_execution_skipped",
                    reason="kill_switch_enabled",
                    signal_id=candidate.signal_id,
                )
                continue
            decision = self._risk_gate.evaluate(candidate, STATE)
            STATE.last_risk_reason = decision.reason
            if not decision.allowed:
                continue
            events.append(self._engine.execute(candidate, STATE))
        await self.position_monitor()
        await self.price_updater()
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
    for _ in range(max(iterations, 1)):
        events = await worker.run_once()
        log.info("paper_beta_worker_iteration", positions=len(STATE.positions), events=events)
        await asyncio.sleep(0)
