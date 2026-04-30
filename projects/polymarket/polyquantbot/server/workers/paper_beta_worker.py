"""Public paper beta worker flow: sync -> signal -> risk -> position -> update.

P8-C hardening:
- Accepts Union[PaperRiskGate, CapitalRiskGate] via duck-typed protocol
- price_updater() raises LiveExecutionBlockedError when STATE.mode == 'live'
  (no-op stub is only valid in paper mode)
- LiveExecutionGuard is checked before any execute() call when mode == 'live'

real-clob-execution-path hardening:
- Optional clob_adapter slot (ClobExecutionAdapter) for real/mocked CLOB submission in live mode
- price_updater_live() accepts a MarketDataProvider for real mark-to-market in live mode
- price_updater() paper path unchanged; live path now delegates to market_data_provider when set
"""
from __future__ import annotations

import asyncio
from collections import Counter
from typing import Union

import structlog

from projects.polymarket.polyquantbot.configs.falcon import FalconSettings
from projects.polymarket.polyquantbot.server.core.live_execution_control import (
    LiveExecutionBlockedError,
    LiveExecutionGuard,
    disable_live_execution,
)
from projects.polymarket.polyquantbot.server.core.public_beta_state import STATE, WorkerIterationSummary
from projects.polymarket.polyquantbot.server.data.live_market_data import (
    LiveMarketDataGuard,
    LiveMarketDataUnavailableError,
    MarketDataProvider,
    StaleMarketDataError,
)
from projects.polymarket.polyquantbot.server.execution.clob_execution_adapter import (
    ClobExecutionAdapter,
    ClobSubmissionBlockedError,
    ClobSubmissionError,
)
from projects.polymarket.polyquantbot.server.execution.paper_execution import PaperExecutionEngine
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import FalconGateway
from projects.polymarket.polyquantbot.server.portfolio.paper_portfolio import PaperPortfolio, _register_portfolio
from projects.polymarket.polyquantbot.server.risk.capital_risk_gate import CapitalRiskGate, WalletFinancialProvider
from projects.polymarket.polyquantbot.server.risk.paper_risk_gate import PaperRiskGate
from projects.polymarket.polyquantbot.server.risk.portfolio_financial_provider import PortfolioFinancialProvider

log = structlog.get_logger(__name__)

# Type alias — worker accepts either gate; CapitalRiskGate is required for live mode
AnyRiskGate = Union[PaperRiskGate, CapitalRiskGate]


class PaperBetaWorker:
    def __init__(
        self,
        falcon: FalconGateway,
        risk_gate: AnyRiskGate,
        engine: PaperExecutionEngine,
        live_guard: LiveExecutionGuard | None = None,
        provider: WalletFinancialProvider | None = None,
        clob_adapter: ClobExecutionAdapter | None = None,
        market_data_provider: MarketDataProvider | None = None,
    ) -> None:
        self._falcon = falcon
        self._risk_gate = risk_gate
        self._engine = engine
        self._live_guard = live_guard
        self._provider = provider
        self._clob_adapter = clob_adapter
        self._market_data_provider = market_data_provider

    async def run_once(self) -> list[dict[str, object]]:
        await self.market_sync()
        candidates = await self.signal_runner()
        events: list[dict[str, object]] = []
        risk_rejection_reasons: Counter[str] = Counter()
        summary = WorkerIterationSummary(candidate_count=len(candidates))

        for candidate in candidates:
            if STATE.mode != "paper":
                # Live execution path: LiveExecutionGuard must pass before any order
                if self._live_guard is not None:
                    resolved_provider: WalletFinancialProvider = (
                        self._provider if self._provider is not None else PortfolioFinancialProvider(STATE)
                    )
                    try:
                        self._live_guard.check(STATE, provider=resolved_provider)
                    except LiveExecutionBlockedError as exc:
                        STATE.last_risk_reason = f"live_guard_blocked:{exc.reason}"
                        summary.skip_mode_count += 1
                        log.warning(
                            "paper_beta_worker_live_guard_blocked",
                            reason=exc.reason,
                            detail=exc.detail,
                            signal_id=candidate.signal_id,
                        )
                        # Trigger rollback/disable path on guard failure
                        disable_live_execution(STATE, reason=exc.reason, detail=exc.detail)
                        continue
                else:
                    # No live guard injected — block all live execution attempts
                    STATE.last_risk_reason = "mode_live_no_guard_injected"
                    summary.skip_mode_count += 1
                    log.error(
                        "paper_beta_worker_live_no_guard",
                        signal_id=candidate.signal_id,
                        execution_boundary="live_guard_required",
                    )
                    disable_live_execution(
                        STATE,
                        reason="no_live_guard_injected",
                        detail="LiveExecutionGuard was not injected; live execution is unsafe without it",
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

            if STATE.mode != "paper" and self._clob_adapter is not None:
                # Live mode with CLOB adapter — submit real/mocked order
                resolved_provider_for_adapter: WalletFinancialProvider = (
                    self._provider if self._provider is not None else PortfolioFinancialProvider(STATE)
                )
                token_id = str(getattr(candidate, "condition_id", ""))
                try:
                    clob_result = await self._clob_adapter.submit_order(
                        state=STATE,
                        signal=candidate,
                        token_id=token_id,
                        provider=resolved_provider_for_adapter,
                    )
                    event = {
                        "mode": clob_result.mode,
                        "condition_id": clob_result.condition_id,
                        "token_id": clob_result.token_id,
                        "side": clob_result.side,
                        "size": clob_result.size,
                        "price": clob_result.price,
                        "order_id": clob_result.order_id,
                        "status": clob_result.status,
                        "dedup_key": clob_result.dedup_key,
                    }
                    summary.accepted_count += 1
                    events.append(event)
                    log.info(
                        "paper_beta_worker_clob_order_submitted",
                        signal_id=candidate.signal_id,
                        order_id=clob_result.order_id,
                        condition_id=clob_result.condition_id,
                        side=clob_result.side,
                        mode=clob_result.mode,
                        status=clob_result.status,
                    )
                except ClobSubmissionBlockedError as exc:
                    STATE.last_risk_reason = f"clob_blocked:{exc.reason}"
                    summary.skip_mode_count += 1
                    log.warning(
                        "paper_beta_worker_clob_submission_blocked",
                        reason=exc.reason,
                        signal_id=candidate.signal_id,
                    )
                except ClobSubmissionError as exc:
                    STATE.last_risk_reason = "clob_submission_error"
                    summary.skip_mode_count += 1
                    log.error(
                        "paper_beta_worker_clob_submission_error",
                        error=str(exc),
                        signal_id=candidate.signal_id,
                    )
            else:
                # Paper mode — use paper execution engine
                event = await self._engine.execute(candidate, STATE)
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
        # price_updater() is a no-op stub — unsafe in live mode; skip it to keep the
        # worker loop deterministic. Direct calls to price_updater() in live mode still raise.
        if STATE.mode == "live":
            log.info(
                "paper_beta_worker_price_updater_skipped_live_mode",
                mode=STATE.mode,
                kill_switch=STATE.kill_switch,
            )
        else:
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
            wallet_cash=STATE.wallet_cash,
            wallet_equity=STATE.wallet_equity,
            realized_pnl=STATE.realized_pnl,
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
        """Update unrealized PnL for open positions.

        In paper mode: no-op stub (live mark-to-market deferred to market data integration).
        In live mode:
          - If market_data_provider is set: delegates to price_updater_live().
          - If no provider: raises LiveExecutionBlockedError (stub unsafe for real capital).

        Raises:
            LiveExecutionBlockedError: When STATE.mode == 'live' and no provider is set.
        """
        if STATE.mode == "live":
            if self._market_data_provider is not None:
                await self.price_updater_live(self._market_data_provider)
                return
            reason = "price_updater_stub_live_mode_blocked"
            detail = (
                "price_updater() is a no-op stub and must not run in live mode — "
                "unrealized PnL would be stale with real capital at risk. "
                "Inject a real MarketDataProvider to enable live mark-to-market."
            )
            log.error(
                "price_updater_live_mode_blocked",
                reason=reason,
                detail=detail,
                open_positions=len(STATE.positions),
            )
            disable_live_execution(STATE, reason=reason, detail=detail)
            raise LiveExecutionBlockedError(reason=reason, detail=detail)
        # Paper mode: safe no-op
        await asyncio.sleep(0)

    async def price_updater_live(self, provider: MarketDataProvider) -> None:
        """Update unrealized PnL using real market prices from a live provider.

        Iterates open positions and fetches the current price from provider.
        Stale prices and unavailable data are logged and skipped (position PnL
        is not updated rather than using stale data).

        Args:
            provider: MarketDataProvider — must be a real (non-stub) implementation
                      when called in live mode. Guarded by LiveMarketDataGuard.

        Raises:
            LiveMarketDataUnavailableError: Provider is a paper stub in live mode.
        """
        guarded = LiveMarketDataGuard(provider=provider, mode=STATE.mode)
        updated = 0
        skipped = 0
        for position in list(STATE.positions):
            token_id = str(getattr(position, "condition_id", ""))
            try:
                market_price = await guarded.get_price(token_id)
                if hasattr(position, "unrealized_pnl") and hasattr(position, "entry_price"):
                    entry = float(position.entry_price)
                    size = float(getattr(position, "size", 0.0))
                    pnl = (market_price.price - entry) * size
                    object.__setattr__(position, "unrealized_pnl", pnl)
                updated += 1
            except (StaleMarketDataError, LiveMarketDataUnavailableError) as exc:
                skipped += 1
                log.warning(
                    "price_updater_live_price_skipped",
                    token_id=token_id,
                    error=str(exc),
                    open_positions=len(STATE.positions),
                )
        log.info(
            "price_updater_live_complete",
            updated=updated,
            skipped=skipped,
            open_positions=len(STATE.positions),
            mode=STATE.mode,
        )


async def run_worker_loop(iterations: int = 1) -> None:
    falcon = FalconGateway(FalconSettings.from_env())

    # Build real engine stack and register as active singleton for operator /reset
    portfolio = PaperPortfolio()
    _register_portfolio(portfolio)
    engine = PaperExecutionEngine(portfolio)

    worker = PaperBetaWorker(
        falcon=falcon,
        risk_gate=PaperRiskGate(),
        engine=engine,
        # live_guard is None in paper worker loop — paper mode only
        live_guard=None,
    )

    # Initialise STATE wallet fields from real engine
    portfolio.sync_state(STATE)

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
        wallet_equity=STATE.wallet_equity,
        wallet_cash=STATE.wallet_cash,
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
                wallet_cash=STATE.wallet_cash,
                wallet_equity=STATE.wallet_equity,
                realized_pnl=STATE.realized_pnl,
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
