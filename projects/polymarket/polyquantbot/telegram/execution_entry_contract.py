from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass

import structlog

from ..execution.engine import ExecutionEngine, export_execution_payload, get_execution_engine
from .handlers.portfolio_service import get_portfolio_service

log = structlog.get_logger(__name__)

_DEFAULT_MARKET = "paper_test_market"
_DEFAULT_SIDE = "YES"
_DEFAULT_SIZE = 25.0
_EXECUTION_PRICE = 0.42
_MARK_PRICE = 0.46
_MAX_CONCURRENT_TRADES = 5
_MARKET_PATTERN = re.compile(r"^[A-Za-z0-9:_\-.]{3,128}$")


@dataclass(frozen=True)
class ExecutionEntry:
    market: str
    side: str
    size: float
    source: str
    signature: str


@dataclass(frozen=True)
class ExecutionEntryResult:
    success: bool
    message: str
    reason: str
    payload: dict
    pipeline_path: tuple[str, str, str]


class TelegramExecutionEntryService:
    """Unified Telegram ENTRY→RISK→EXECUTION bounded contract."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._seen_signatures: set[str] = set()

    def parse_command_test_args(self, args: str) -> ExecutionEntryResult | ExecutionEntry:
        parts = [part for part in args.split() if part]
        if len(parts) < 3:
            return ExecutionEntryResult(
                success=False,
                message="Usage: /trade test [market] [side YES/NO] [size]",
                reason="invalid_command_args",
                payload={},
                pipeline_path=("entry", "risk", "execution"),
            )
        market, side_raw, size_raw = parts[0], parts[1], parts[2]
        return self._normalize_entry(market=market, side=side_raw, size_raw=size_raw, source="telegram_command")

    def callback_default_entry(self, market_hint: str | None = None) -> ExecutionEntryResult | ExecutionEntry:
        market = (market_hint or _DEFAULT_MARKET).strip()
        return self._normalize_entry(
            market=market,
            side=_DEFAULT_SIDE,
            size_raw=str(_DEFAULT_SIZE),
            source="telegram_callback",
        )

    def _normalize_entry(
        self,
        *,
        market: str,
        side: str,
        size_raw: str,
        source: str,
    ) -> ExecutionEntryResult | ExecutionEntry:
        normalized_market = market.strip()
        if not normalized_market or not _MARKET_PATTERN.match(normalized_market):
            return ExecutionEntryResult(
                success=False,
                message="Invalid market format. Use letters, numbers, :, _, -, .",
                reason="invalid_market",
                payload={},
                pipeline_path=("entry", "risk", "execution"),
            )
        normalized_side = side.strip().upper()
        if normalized_side not in {"YES", "NO"}:
            return ExecutionEntryResult(
                success=False,
                message="Side must be YES or NO.",
                reason="invalid_side",
                payload={},
                pipeline_path=("entry", "risk", "execution"),
            )
        try:
            normalized_size = float(size_raw)
        except ValueError:
            return ExecutionEntryResult(
                success=False,
                message="Size must be a number.",
                reason="invalid_size",
                payload={},
                pipeline_path=("entry", "risk", "execution"),
            )
        if normalized_size <= 0:
            return ExecutionEntryResult(
                success=False,
                message="Size must be greater than 0.",
                reason="size_non_positive",
                payload={},
                pipeline_path=("entry", "risk", "execution"),
            )

        signature = f"{normalized_market}:{normalized_side}:{normalized_size:.6f}"
        return ExecutionEntry(
            market=normalized_market,
            side=normalized_side,
            size=normalized_size,
            source=source,
            signature=signature,
        )

    async def execute(self, entry: ExecutionEntry, engine: ExecutionEngine | None = None) -> ExecutionEntryResult:
        bounded_engine = engine or get_execution_engine()
        async with self._lock:
            snapshot = await bounded_engine.snapshot()

            if entry.signature in self._seen_signatures:
                log.warning("telegram_execution_entry_duplicate", signature=entry.signature, source=entry.source)
                return ExecutionEntryResult(
                    success=False,
                    message="Duplicate execution blocked.",
                    reason="duplicate_entry",
                    payload={},
                    pipeline_path=("entry", "risk", "execution"),
                )

            if len(snapshot.positions) >= _MAX_CONCURRENT_TRADES:
                return ExecutionEntryResult(
                    success=False,
                    message="Execution blocked: max concurrent trades reached.",
                    reason="max_concurrent_trades",
                    payload={},
                    pipeline_path=("entry", "risk", "execution"),
                )

            if any(pos.market_id == entry.market for pos in snapshot.positions):
                return ExecutionEntryResult(
                    success=False,
                    message="Execution blocked: market already has an open position.",
                    reason="duplicate_market_position",
                    payload={},
                    pipeline_path=("entry", "risk", "execution"),
                )

            max_position_size = max(snapshot.equity, 0.0) * bounded_engine.max_position_size_ratio
            if entry.size > max_position_size:
                return ExecutionEntryResult(
                    success=False,
                    message="Execution blocked: size exceeds max position limit.",
                    reason="max_position_exceeded",
                    payload={},
                    pipeline_path=("entry", "risk", "execution"),
                )

            created = await bounded_engine.open_position(
                market=entry.market,
                side=entry.side,
                price=_EXECUTION_PRICE,
                size=entry.size,
                position_id=f"tg-{uuid.uuid4()}",
            )
            if created is None:
                return ExecutionEntryResult(
                    success=False,
                    message="Execution blocked by engine safeguards.",
                    reason="engine_rejected",
                    payload={},
                    pipeline_path=("entry", "risk", "execution"),
                )

            self._seen_signatures.add(entry.signature)

            await bounded_engine.update_mark_to_market({entry.market: _MARK_PRICE})
            payload = await export_execution_payload()
            get_portfolio_service().merge_execution_state(
                positions=payload.get("positions", []),
                cash=float(payload.get("cash", 0.0)),
                equity=float(payload.get("equity", 0.0)),
                realized_pnl=float(payload.get("realized", 0.0)),
            )
            return ExecutionEntryResult(
                success=True,
                message=f"Paper execution submitted: {entry.market} {entry.side} ${entry.size:.2f}",
                reason="executed",
                payload=payload,
                pipeline_path=("entry", "risk", "execution"),
            )


_service_singleton: TelegramExecutionEntryService | None = None


def get_telegram_execution_entry_service() -> TelegramExecutionEntryService:
    global _service_singleton  # noqa: PLW0603
    if _service_singleton is None:
        _service_singleton = TelegramExecutionEntryService()
    return _service_singleton
