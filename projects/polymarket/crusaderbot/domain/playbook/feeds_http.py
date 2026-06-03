"""PLAYBOOK external-feed reference adapters (Phase-2d/2e).

Concrete ``SportsFeed`` implementations behind the Phase-1 Protocol (``feeds.py``).
Two free reference providers are wired:

* **ESPN public endpoints** (no key) → injury / lineup events for Injury Alpha.
* **The Odds API** (free tier, ``ODDS_API_KEY`` from env) → a no-vig consensus
  model probability and a soft-vs-sharp book *public-lean* proxy for Public Fade.
  Genuine public-ticket% feeds are paywalled; the sharp/soft divergence
  (Pinnacle vs DraftKings) is the free, defensible proxy.

Design contract (matches the WARP-53 locked decision — pluggable adapters):

* Every external call is wrapped ``httpx`` with timeout + fail-soft try/except,
  returning ``None`` on any error so a feed problem never breaks the scan loop or
  flips a trade direction (mirrors ``strategies/weather/forecast.py``).
* The API key is read from the environment *inside* the adapter only — never
  stored on ``Settings`` (mirrors ``VISUALCROSSING_API_KEY``).
* A Polymarket ``market_id`` does not by itself address an ESPN team or an Odds
  API event, so the live path needs a ``MarketResolver`` (``market_id`` →
  ``FeedTarget``). ``build_sports_feed`` returns ``NullFeed`` unless feeds are
  enabled *and* a resolver is supplied — so production stays network-free and
  paper-only until the operator provisions a key, the network allowlist, and a
  resolver. The parsers below are pure + unit-tested independently of all that.

This module is intentionally kept out of ``domain/playbook/__init__`` so the
decision core stays import-light (same posture as ``sharp_flow.py``).
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable

import httpx
import structlog

from .feeds import InjuryEvent, NullFeed, PublicFlow, SportsFeed

logger = structlog.get_logger(__name__)

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"
_ODDS_API_BASE = "https://api.the-odds-api.com/v4/sports"

# ESPN injury status → severity magnitude in [0, 1] (impact on the outcome prob).
_ESPN_STATUS_SEVERITY: dict[str, float] = {
    "out": 1.0,
    "injured reserve": 1.0,
    "suspension": 1.0,
    "doubtful": 0.75,
    "day-to-day": 0.4,
    "questionable": 0.4,
    "probable": 0.2,
}


@dataclass(frozen=True)
class FeedTarget:
    """Resolves a Polymarket ``market_id`` to its external feed addressing.

    Watches a single team (``espn_team_id``) and the single Odds API event that
    underlies the market. ``injury_yes_favored`` records whether an injury to the
    watched team *raises* P(YES) — usually ``False`` when the watched team is the
    YES side (their injury hurts YES). ``yes_outcome_name`` maps the Odds API h2h
    outcome that corresponds to the market's YES leg.
    """

    market_id: str
    # ESPN injury addressing
    espn_sport: str = ""  # e.g. "basketball"
    espn_league: str = ""  # e.g. "nba"
    espn_team_id: str = ""  # ESPN team whose injuries move this market
    injury_yes_favored: bool = False
    # The Odds API addressing
    oddsapi_sport_key: str = ""  # e.g. "basketball_nba"
    oddsapi_event_id: str = ""
    yes_outcome_name: str = ""  # h2h outcome name corresponding to YES
    public_book: str = "draftkings"
    sharp_book: str = "pinnacle"


@runtime_checkable
class MarketResolver(Protocol):
    """Maps a Polymarket ``market_id`` to a ``FeedTarget`` (or None if unknown)."""

    def __call__(self, market_id: str) -> FeedTarget | None: ...


# ---------------------------------------------------------------------------
# Pure parsers (no network / no clock except an injected now) — unit-tested.
# ---------------------------------------------------------------------------


def decimal_to_implied(decimal_odds: float) -> float | None:
    """Implied probability from decimal odds (``1/odds``); None if non-positive."""
    try:
        o = float(decimal_odds)
    except (TypeError, ValueError):
        return None
    return 1.0 / o if o > 0.0 else None


def devig_two_way(p_a: float, p_b: float) -> tuple[float, float] | None:
    """Remove the bookmaker overround from a two-way market (normalise to 1)."""
    total = p_a + p_b
    if total <= 0.0:
        return None
    return p_a / total, p_b / total


def _book_outcome_price(
    payload: dict[str, Any], book_key: str, outcome_name: str
) -> float | None:
    """Decimal price for ``outcome_name`` in ``book_key``'s h2h market, or None."""
    if not isinstance(payload, dict):
        return None
    for bk in payload.get("bookmakers") or []:
        if not isinstance(bk, dict) or str(bk.get("key", "")).lower() != book_key.lower():
            continue
        for mkt in bk.get("markets") or []:
            if not isinstance(mkt, dict) or mkt.get("key") != "h2h":
                continue
            for oc in mkt.get("outcomes") or []:
                if isinstance(oc, dict) and str(oc.get("name", "")).lower() == outcome_name.lower():
                    try:
                        return float(oc["price"])
                    except (KeyError, TypeError, ValueError):
                        return None
    return None


def _two_way_names(payload: dict[str, Any], book_key: str) -> list[str]:
    """Ordered outcome names of ``book_key``'s h2h market (for the other side)."""
    if not isinstance(payload, dict):
        return []
    for bk in payload.get("bookmakers") or []:
        if not isinstance(bk, dict) or str(bk.get("key", "")).lower() != book_key.lower():
            continue
        for mkt in bk.get("markets") or []:
            if isinstance(mkt, dict) and mkt.get("key") == "h2h":
                return [str(o.get("name", "")) for o in (mkt.get("outcomes") or []) if isinstance(o, dict)]
    return []


def parse_oddsapi_model_probability(
    payload: dict[str, Any], *, yes_outcome_name: str, side: str
) -> float | None:
    """No-vig consensus P(side) averaged across every book quoting the event.

    For each book, de-vig the two-way h2h to a fair probability for the YES
    outcome, then average across books. ``side`` selects YES (the averaged prob)
    or NO (its complement). Returns None when no book quotes a clean two-way.
    """
    s = (side or "").strip().upper()
    if s not in ("YES", "NO") or not yes_outcome_name or not isinstance(payload, dict):
        return None
    fair_yes: list[float] = []
    for bk in payload.get("bookmakers") or []:
        if not isinstance(bk, dict):
            continue
        book_key = str(bk.get("key", ""))
        names = _two_way_names(payload, book_key)
        if len(names) != 2:
            continue
        other = next((n for n in names if n.lower() != yes_outcome_name.lower()), "")
        p_yes = decimal_to_implied(_book_outcome_price(payload, book_key, yes_outcome_name))
        p_oth = decimal_to_implied(_book_outcome_price(payload, book_key, other))
        if p_yes is None or p_oth is None:
            continue
        devig = devig_two_way(p_yes, p_oth)
        if devig is not None:
            fair_yes.append(devig[0])
    if not fair_yes:
        return None
    avg_yes = sum(fair_yes) / len(fair_yes)
    return avg_yes if s == "YES" else (1.0 - avg_yes)


def parse_oddsapi_public_flow(
    payload: dict[str, Any],
    market_id: str,
    *,
    yes_outcome_name: str,
    public_book: str,
    sharp_book: str,
    lean_scale: float = 0.10,
) -> PublicFlow | None:
    """Public-lean proxy from soft-vs-sharp book divergence on the YES outcome.

    When the soft/public book prices the YES outcome at a *higher* implied
    probability than the sharp book, the public is leaning YES (and vice-versa).
    The divergence ``|p_soft − p_sharp|`` is mapped to a public share in
    ``[0.5, 1.0]`` via ``lean_scale`` (a full ``lean_scale`` gap ⇒ 100% lean).
    Returns None when either book is missing the outcome. Pure — no network.
    """
    if not yes_outcome_name:
        return None
    names = _two_way_names(payload, public_book) or _two_way_names(payload, sharp_book)
    other = next((n for n in names if n.lower() != yes_outcome_name.lower()), "")
    p_soft_yes = decimal_to_implied(_book_outcome_price(payload, public_book, yes_outcome_name))
    p_sharp_yes = decimal_to_implied(_book_outcome_price(payload, sharp_book, yes_outcome_name))
    if p_soft_yes is None or p_sharp_yes is None:
        return None
    diff = p_soft_yes - p_sharp_yes  # >0 → public over-likes YES vs the sharp line
    if diff == 0.0:
        return PublicFlow(market_id=market_id, public_pct_on_side=0.5, side="YES")
    side = "YES" if diff > 0 else "NO"
    pct = 0.5 + 0.5 * min(1.0, abs(diff) / lean_scale) if lean_scale > 0 else 0.5
    _ = other  # reserved for richer multi-book weighting; kept for clarity
    return PublicFlow(market_id=market_id, public_pct_on_side=round(pct, 4), side=side)


def parse_espn_injury_payload(
    payload: dict[str, Any],
    market_id: str,
    *,
    yes_favored: bool,
    now_epoch: float,
    max_age_sec: float = 86_400.0,
) -> InjuryEvent | None:
    """Most-severe recent injury record from an ESPN team-injuries payload.

    Tolerant of ESPN's nested shapes: a top-level ``injuries`` list, a per-team
    ``{"injuries": [...]}`` wrapper, or an ``items`` list. Each record's
    ``status`` maps to a severity; ``date`` sets the detection time. Records older
    than ``max_age_sec`` or with an unknown status are ignored. Returns the single
    highest-severity in-window event, or None.
    """
    if not isinstance(payload, dict):
        return None
    records: list[dict[str, Any]] = []
    raw = payload.get("injuries")
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict) and isinstance(entry.get("injuries"), list):
                records.extend(e for e in entry["injuries"] if isinstance(e, dict))
            elif isinstance(entry, dict):
                records.append(entry)
    if not records and isinstance(payload.get("items"), list):
        records = [e for e in payload["items"] if isinstance(e, dict)]

    best: InjuryEvent | None = None
    best_sev = 0.0
    for rec in records:
        status = str(rec.get("status") or "").strip().lower()
        if not status and isinstance(rec.get("type"), dict):
            status = str(rec["type"].get("name") or "").strip().lower()
        severity = _ESPN_STATUS_SEVERITY.get(status, 0.0)
        if severity <= 0.0:
            continue
        # Require a parseable, in-window timestamp — a missing/garbled date must
        # not be treated as brand-new (that would let a stale injury read fresh).
        ts = _parse_epoch(rec.get("date") or rec.get("updated") or rec.get("lastModified"))
        if ts is None or now_epoch - ts > max_age_sec:
            continue
        if severity > best_sev:
            athlete = rec.get("athlete") or {}
            name = athlete.get("displayName") if isinstance(athlete, dict) else ""
            headline = str(rec.get("shortComment") or rec.get("longComment") or name or status)
            best = InjuryEvent(
                market_id=market_id,
                headline=headline[:200],
                severity=severity,
                detected_ts_epoch=ts,
                yes_favored=yes_favored,
                repriced_fraction=0.0,
            )
            best_sev = severity
    return best


def _parse_epoch(ts: object) -> float | None:
    """ISO-8601 (tolerating a trailing Z) → unix seconds; None on failure."""
    if ts in (None, ""):
        return None
    from datetime import datetime, timezone

    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


# ---------------------------------------------------------------------------
# HTTP adapters (fail-soft) + composite feed + factory.
# ---------------------------------------------------------------------------


class EspnInjuryFeed:
    """Injury events from ESPN's free public team-injuries endpoint."""

    def __init__(self, resolver: MarketResolver) -> None:
        self._resolver = resolver

    async def get_injury_event(self, market_id: str) -> InjuryEvent | None:
        target = self._resolver(market_id)
        if target is None or not (target.espn_sport and target.espn_league and target.espn_team_id):
            return None
        url = (
            f"{_ESPN_BASE}/{target.espn_sport}/{target.espn_league}"
            f"/teams/{target.espn_team_id}/injuries"
        )
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                payload = resp.json()
        except Exception as exc:  # noqa: BLE001 — fail-soft, never break the scan loop
            logger.warning("playbook_espn_injury_fetch_failed", market=market_id, error=str(exc))
            return None
        return parse_espn_injury_payload(
            payload, market_id, yes_favored=target.injury_yes_favored, now_epoch=time.time()
        )

    async def get_public_flow(self, market_id: str) -> PublicFlow | None:
        return None

    async def get_model_probability(self, market_id: str, side: str) -> float | None:
        return None


class OddsApiFeed:
    """Consensus model probability + public-lean proxy from The Odds API."""

    def __init__(self, resolver: MarketResolver, *, api_key: str) -> None:
        self._resolver = resolver
        self._api_key = api_key

    async def _fetch_event_odds(self, target: FeedTarget) -> dict[str, Any] | None:
        if not (target.oddsapi_sport_key and target.oddsapi_event_id):
            return None
        url = f"{_ODDS_API_BASE}/{target.oddsapi_sport_key}/events/{target.oddsapi_event_id}/odds"
        params = {
            "apiKey": self._api_key,
            "regions": "us,eu",
            "markets": "h2h",
            "oddsFormat": "decimal",
            "bookmakers": f"{target.sharp_book},{target.public_book}",
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:  # noqa: BLE001 — fail-soft
            logger.warning("playbook_oddsapi_fetch_failed", market=target.market_id, error=str(exc))
            return None

    async def get_injury_event(self, market_id: str) -> InjuryEvent | None:
        return None

    async def get_public_flow(self, market_id: str) -> PublicFlow | None:
        target = self._resolver(market_id)
        if target is None or not target.yes_outcome_name:
            return None
        payload = await self._fetch_event_odds(target)
        if payload is None:
            return None
        return parse_oddsapi_public_flow(
            payload,
            market_id,
            yes_outcome_name=target.yes_outcome_name,
            public_book=target.public_book,
            sharp_book=target.sharp_book,
        )

    async def get_model_probability(self, market_id: str, side: str) -> float | None:
        target = self._resolver(market_id)
        if target is None or not target.yes_outcome_name:
            return None
        payload = await self._fetch_event_odds(target)
        if payload is None:
            return None
        return parse_oddsapi_model_probability(
            payload, yes_outcome_name=target.yes_outcome_name, side=side
        )


class HttpSportsFeed:
    """Composite ``SportsFeed`` routing each lookup to its provider, fail-soft."""

    def __init__(self, *, injury: SportsFeed | None, odds: SportsFeed | None) -> None:
        self._injury = injury
        self._odds = odds

    async def get_injury_event(self, market_id: str) -> InjuryEvent | None:
        return await self._injury.get_injury_event(market_id) if self._injury else None

    async def get_public_flow(self, market_id: str) -> PublicFlow | None:
        return await self._odds.get_public_flow(market_id) if self._odds else None

    async def get_model_probability(self, market_id: str, side: str) -> float | None:
        return await self._odds.get_model_probability(market_id, side) if self._odds else None


def build_sports_feed(
    settings: Any, resolver: MarketResolver | None = None
) -> SportsFeed:
    """Construct the active ``SportsFeed`` from config, defaulting to ``NullFeed``.

    Returns ``NullFeed`` (no network) unless a ``resolver`` is supplied AND the
    relevant feed flag is on. The injury feed activates on
    ``PLAYBOOK_INJURY_FEED_ENABLED``; the odds feed on
    ``PLAYBOOK_PUBLIC_FEED_ENABLED`` AND a non-empty ``ODDS_API_KEY`` in the env
    (read here only, never stored on Settings). This keeps CI + production inert
    and paper-only until the operator provisions every dependency.
    """
    if resolver is None:
        return NullFeed()
    injury_on = bool(getattr(settings, "PLAYBOOK_INJURY_FEED_ENABLED", False))
    public_on = bool(getattr(settings, "PLAYBOOK_PUBLIC_FEED_ENABLED", False))
    odds_key = os.getenv("ODDS_API_KEY", "").strip()

    injury_feed: SportsFeed | None = EspnInjuryFeed(resolver) if injury_on else None
    odds_feed: SportsFeed | None = (
        OddsApiFeed(resolver, api_key=odds_key) if (public_on and odds_key) else None
    )
    if injury_feed is None and odds_feed is None:
        return NullFeed()
    return HttpSportsFeed(injury=injury_feed, odds=odds_feed)


__all__ = [
    "FeedTarget",
    "MarketResolver",
    "EspnInjuryFeed",
    "OddsApiFeed",
    "HttpSportsFeed",
    "build_sports_feed",
    "decimal_to_implied",
    "devig_two_way",
    "parse_oddsapi_model_probability",
    "parse_oddsapi_public_flow",
    "parse_espn_injury_payload",
]
