"""Falcon read-side integration for paper beta worker and control plane."""
from __future__ import annotations

from dataclasses import dataclass

from projects.polymarket.polyquantbot.configs.falcon import FalconSettings
from projects.polymarket.polyquantbot.data.ingestion.falcon_alpha import FalconAPIClient, fetch_external_alpha_with_fallback


@dataclass(frozen=True)
class CandidateSignal:
    signal_id: str
    condition_id: str
    side: str
    edge: float
    liquidity: float
    price: float


class FalconGateway:
    def __init__(self, settings: FalconSettings) -> None:
        self._settings = settings
        self._client = FalconAPIClient(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout_seconds=settings.timeout_seconds,
        )

    async def list_markets(self, query: str = "") -> list[dict[str, object]]:
        if not self._settings.enabled:
            return []
        sample = [
            {"condition_id": "cond-1", "title": "Will BTC close above 80k?"},
            {"condition_id": "cond-2", "title": "Will ETH ETF inflows stay positive?"},
        ]
        if not query:
            return sample
        q = query.lower()
        return [item for item in sample if q in str(item["title"]).lower()]

    async def market_360(self, condition_id: str) -> dict[str, object]:
        alpha = await fetch_external_alpha_with_fallback(
            self._client,
            market_id=condition_id,
            token_id=condition_id,
        )
        return {"condition_id": condition_id, "alpha": alpha}

    async def social(self, topic: str) -> dict[str, object]:
        return {
            "topic": topic,
            "summary": "Falcon social narrative summary unavailable in beta; using safe placeholder.",
        }

    async def rank_candidates(self) -> list[CandidateSignal]:
        if not self._settings.enabled:
            return []
        return [
            CandidateSignal("sig-cond-1", "cond-1", "YES", edge=0.034, liquidity=25000.0, price=0.62),
            CandidateSignal("sig-cond-2", "cond-2", "NO", edge=0.018, liquidity=9000.0, price=0.41),
        ]
